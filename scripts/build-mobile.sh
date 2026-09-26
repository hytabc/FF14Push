#!/usr/bin/env bash
#
# 三端一键构建：Android APK / iOS IPA / HarmonyOS HAP。
#
#   ./scripts/build-mobile.sh                  # 预检 → 构建 → 汇总
#   ./scripts/build-mobile.sh --check          # 只预检，并列出「需要你补充」的内容（不构建）
#   ./scripts/build-mobile.sh --only android,hap
#   ./scripts/build-mobile.sh --skip-preflight # 环境已知 OK 时跳过预检
#   npm run app:all                            # 等价 ./scripts/build-mobile.sh
#
# 本脚本**只做编排与预检提示**，真正的构建仍在三个单端脚本里（它们才是权威校验，
# 例如 build-apk.sh 会真正核对 JDK 版本与 jlink）：
#   scripts/build-apk.sh / scripts/build-ios.sh / scripts/build-hap.sh
#
# 缺「硬前置」（Xcode / Apple 签名 / DevEco / Java）→ 跳过该端并给出补充步骤；
# 缺「软前置」（Android 发布密钥、鸿蒙签名）→ 照常构建，但汇总里标 ⚠ 说明产物性质。
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

DEVECO_HOME_DEFAULT="/Applications/DevEco-Studio.app/Contents"

# ── 输出样式 ──────────────────────────────────────────────────────────
if [[ -t 1 ]]; then
  C_DIM=$'\033[2m'; C_CYAN=$'\033[36m'; C_GREEN=$'\033[32m'; C_RED=$'\033[31m'; C_YELLOW=$'\033[33m'; C_BOLD=$'\033[1m'; C_OFF=$'\033[0m'
else
  C_DIM=''; C_CYAN=''; C_GREEN=''; C_RED=''; C_YELLOW=''; C_BOLD=''; C_OFF=''
fi

step() { printf '\n%s[%s]%s %s\n' "$C_BOLD$C_CYAN" "$1" "$C_OFF" "$2"; }
ok()   { printf '  %s✔%s %-10s %s\n' "$C_GREEN" "$C_OFF" "$1" "$2"; }
bad()  { printf '  %s✖%s %-10s %s\n' "$C_RED" "$C_OFF" "$1" "$2"; }
warn() { printf '  %s⚠%s %-10s %s\n' "$C_YELLOW" "$C_OFF" "$1" "$2"; }
info() { printf '  %s%s%s\n' "$C_DIM" "$*" "$C_OFF"; }
echo2() { printf '%s\n' "$*"; }

# 需要用户补充的事项（去重后按以下顺序打印）。
GAPS=()
add_gap() {
  local id="$1"
  for existing in ${GAPS[@]+"${GAPS[@]}"}; do
    [[ "$existing" == "$id" ]] && return 0
  done
  GAPS+=("$id")
}

# ── 参数 ──────────────────────────────────────────────────────────────
ALL_PLATFORMS=(android ios hap)
SELECTED=()
CHECK_ONLY=false
SKIP_PREFLIGHT=false

usage() {
  cat <<'EOF'
用法：./scripts/build-mobile.sh [选项]

  --check              只做预检并列出需要补充的内容，不构建
  --only <列表>        只构建指定平台，逗号分隔：android,ios,hap
  --skip-preflight     跳过预检直接构建（已知环境 OK 时）
  -h, --help           显示本帮助

示例：
  ./scripts/build-mobile.sh --check
  ./scripts/build-mobile.sh --only android,hap
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --check) CHECK_ONLY=true; shift ;;
    --skip-preflight) SKIP_PREFLIGHT=true; shift ;;
    --only)
      shift
      [[ $# -gt 0 ]] || { echo2 "缺少 --only 的参数（android,ios,hap）"; exit 2; }
      IFS=',' read -r -a requested <<<"$1"
      for p in "${requested[@]}"; do
        case "$p" in
          android|ios|hap) SELECTED+=("$p") ;;
          *) echo2 "未知平台：${p}（可选 android / ios / hap）"; exit 2 ;;
        esac
      done
      shift
      ;;
    -h|--help) usage; exit 0 ;;
    *) echo2 "未知参数：$1"; usage; exit 2 ;;
  esac
done

if [[ ${#SELECTED[@]} -eq 0 ]]; then
  SELECTED=("${ALL_PLATFORMS[@]}")
fi

is_selected() {
  local want="$1"
  for p in "${SELECTED[@]}"; do [[ "$p" == "$want" ]] && return 0; done
  return 1
}

# ── 小工具 ────────────────────────────────────────────────────────────
java_major() { "$1/bin/java" -version 2>&1 | sed -n '1s/.*version "\([0-9]*\).*/\1/p'; }

# 挑一份可用于 Android 的「完整」JDK（21–24，且带 jlink）。与 build-apk.sh 同规则；
# 这里只用于预检提示，实际校验仍以 build-apk.sh 为准。
pick_android_jdk() {
  local candidates=()
  [[ -n "${JAVA_HOME:-}" ]] && candidates+=("$JAVA_HOME")
  candidates+=(
    "/opt/homebrew/opt/openjdk@21/libexec/openjdk.jdk/Contents/Home"
    "/usr/local/opt/openjdk@21/libexec/openjdk.jdk/Contents/Home"
    "/Library/Java/JavaVirtualMachines/temurin-21.jdk/Contents/Home"
  )
  if [[ -x /usr/libexec/java_home ]]; then
    local h; h="$(/usr/libexec/java_home -v 21 2>/dev/null || true)"
    [[ -n "$h" ]] && candidates+=("$h")
  fi
  local c major
  for c in "${candidates[@]}"; do
    [[ -x "$c/bin/java" && -x "$c/bin/jlink" ]] || continue
    major="$(java_major "$c")"
    [[ -n "$major" ]] || continue
    (( major >= 21 && major <= 24 )) && { echo "$c"; return 0; }
  done
  return 1
}

# 挑一份任意可用的 Java（鸿蒙打包阶段需要）。
pick_any_java() {
  local candidates=(
    "${JAVA_HOME:-}"
    "$DEVECO_HOME_DEFAULT/jbr/Contents/Home"
    "/opt/homebrew/opt/openjdk@21/libexec/openjdk.jdk/Contents/Home"
    "/usr/local/opt/openjdk@21/libexec/openjdk.jdk/Contents/Home"
  )
  local c
  for c in "${candidates[@]}"; do
    [[ -n "$c" && -x "$c/bin/java" ]] && { echo "$c"; return 0; }
  done
  return 1
}

android_sdk() {
  local sdk="${ANDROID_HOME:-${ANDROID_SDK_ROOT:-}}"
  if [[ -z "$sdk" ]]; then
    for c in "$HOME/Library/Android/sdk" "$HOME/Android/Sdk"; do
      [[ -d "$c" ]] && sdk="$c" && break
    done
  fi
  [[ -n "$sdk" && -d "$sdk" ]] && { echo "$sdk"; return 0; }
  return 1
}

# ── 预检：Android ─────────────────────────────────────────────────────
PRE_ANDROID_HARD=false
PRE_ANDROID_KEYSTORE=false
preflight_android() {
  local missing=()
  local jdk sdk
  if jdk="$(pick_android_jdk)"; then
    ok "Android" "JDK $(java_major "$jdk")（${jdk}）"
  else
    bad "Android" "找不到完整可用的 JDK 21–24（需带 jlink）"
    add_gap android-jdk
    missing+=("jdk")
  fi
  if sdk="$(android_sdk)"; then
    ok "Android" "Android SDK（${sdk}）"
  else
    bad "Android" "找不到 Android SDK"
    add_gap android-sdk
    missing+=("sdk")
  fi
  if [[ -f android/keystore/eorzea-release.jks && -f android/keystore.properties ]]; then
    PRE_ANDROID_KEYSTORE=true
    ok "Android" "发布签名已配置（android/keystore）"
  else
    warn "Android" "未配置发布签名 → 仍可构建，但会用 debug 签名（不能覆盖安装线上包）"
    add_gap android-keystore
  fi
  [[ ${#missing[@]} -eq 0 ]] && PRE_ANDROID_HARD=true
}

# ── 预检：iOS ─────────────────────────────────────────────────────────
PRE_IOS_HARD=false
preflight_ios() {
  local missing=()
  local dev_dir
  dev_dir="$(xcode-select -p 2>/dev/null || true)"
  case "$dev_dir" in
    *Xcode*.app/Contents/Developer) ok "iOS" "Xcode（$(xcodebuild -version 2>/dev/null | head -1)）" ;;
    *)
      bad "iOS" "需要完整安装的 Xcode（当前 developer 目录：${dev_dir:-未设置}）"
      add_gap ios-xcode
      missing+=("xcode")
      ;;
  esac

  if [[ -d ios/App/App.xcodeproj ]]; then
    ok "iOS" "Xcode 工程就绪（ios/App/App.xcodeproj）"
  else
    bad "iOS" "缺少 iOS 工程"
    add_gap ios-project
    missing+=("project")
  fi

  local identities
  identities="$(security find-identity -v -p codesigning 2>/dev/null | sed -n 's/.*\([0-9][0-9]*\) valid identities found.*/\1/p' | tail -1)"
  identities="${identities:-0}"
  if (( identities > 0 )); then
    ok "iOS" "钥匙串中有 $identities 个代码签名身份"
  else
    bad "iOS" "钥匙串中没有 Apple 代码签名身份（0 valid identities）"
    add_gap ios-account
    missing+=("identity")
  fi

  local team="${IOS_TEAM_ID:-}"
  if [[ -z "$team" && -f ios/signing.properties ]]; then
    team="$(sed -n 's/^teamId=//p' ios/signing.properties | head -1)"
  fi
  if [[ -n "$team" ]]; then
    ok "iOS" "团队 ID：$team"
  else
    bad "iOS" "未提供团队 ID"
    add_gap ios-team
    missing+=("team")
  fi

  [[ ${#missing[@]} -eq 0 ]] && PRE_IOS_HARD=true
}

# ── 预检：HarmonyOS ───────────────────────────────────────────────────
PRE_HAP_HARD=false
preflight_hap() {
  local missing=()
  local deveco="${DEVECO_HOME:-$DEVECO_HOME_DEFAULT}"
  local hvigorw="$deveco/tools/hvigor/bin/hvigorw"
  local sdk="${DEVECO_SDK_HOME:-$deveco/sdk}"

  if [[ -x "$hvigorw" && -d "$sdk" ]]; then
    ok "HarmonyOS" "DevEco 工具链就绪（hvigor + SDK：${sdk}）"
  else
    bad "HarmonyOS" "找不到 DevEco（hvigor / SDK）。可用 DEVECO_HOME 指定安装目录"
    add_gap hap-toolchain
    missing+=("deveco")
  fi

  local java
  if java="$(pick_any_java)"; then
    ok "HarmonyOS" "Java 运行时（${java}）"
  else
    bad "HarmonyOS" "找不到 Java 运行时（打包阶段需要）"
    add_gap java
    missing+=("java")
  fi

  [[ -d harmony ]] || { bad "HarmonyOS" "缺少 harmony/ 工程"; add_gap hap-project; missing+=("project"); }

  if [[ -f harmony/build-profile.json5 ]] && grep -qi 'certpath' harmony/build-profile.json5; then
    ok "HarmonyOS" "签名已配置"
  else
    warn "HarmonyOS" "未配置签名 → 仍可构建，但只产出未签名 HAP（装不上设备）"
    add_gap hap-signing
  fi

  [[ ${#missing[@]} -eq 0 ]] && PRE_HAP_HARD=true
}

# ── 缺项提示 ──────────────────────────────────────────────────────────
print_gaps() {
  [[ ${#GAPS[@]} -eq 0 ]] && return 0
  printf '\n  %s── 需要你补充（%d 项）──────────────────────────────%s\n' "$C_BOLD" "${#GAPS[@]}" "$C_OFF"
  local index=0
  for gap in "${GAPS[@]}"; do
    index=$((index + 1))
    case "$gap" in
      android-jdk)
        cat <<EOF

  ${C_BOLD}($index) Android：安装可用的 JDK${C_OFF}
      本项目要求 JDK 21–24 且自带 jlink（Android Studio 自带的 JBR 不满足）。
        brew install openjdk@21
      安装后重新执行本脚本即可（脚本会自动探测，无需 export）。
EOF
        ;;
      android-sdk)
        cat <<EOF

  ${C_BOLD}($index) Android：安装 Android SDK${C_OFF}
      推荐装 Android Studio（自带 SDK），或手动安装 SDK 后：
        export ANDROID_HOME="$HOME/Library/Android/sdk"
EOF
        ;;
      android-keystore)
        cat <<EOF

  ${C_BOLD}($index) Android：发布签名（可选，但正式分发需要）${C_OFF}
      现在会用 debug 签名，产物无法覆盖安装线上的发布包。补上正式密钥即可：
        keytool -genkeypair -v -keystore android/keystore/eorzea-release.jks \\
          -alias eorzea -keyalg RSA -keysize 2048 -validity 10000
      再创建 android/keystore.properties（本机私有，不入库）：
        storeFile=keystore/eorzea-release.jks
        storePassword=你的口令
        keyAlias=eorzea
        keyPassword=你的口令
EOF
        ;;
      ios-xcode)
        cat <<EOF

  ${C_BOLD}($index) iOS：安装完整版 Xcode${C_OFF}
      App Store 安装 Xcode 后切换开发者目录：
        sudo xcode-select -s /Applications/Xcode.app/Contents/Developer
EOF
        ;;
      ios-project)
        cat <<EOF

  ${C_BOLD}($index) iOS：生成 Xcode 工程${C_OFF}
        npx cap add ios
EOF
        ;;
      ios-account)
        cat <<EOF

  ${C_BOLD}($index) iOS：登录 Apple ID 生成签名证书${C_OFF}
      1. 打开 Xcode → 菜单 Settings → Accounts → 用 Apple ID 登录
         （付费 Apple Developer Program 才能出 App Store / TestFlight / ad-hoc / 企业包；
           免费账号只能出 7 天有效、需连真机的开发包）
      2. 登录后 Xcode 会自动创建开发证书；也可以把它加入钥匙串：
         Xcode → Settings → Accounts → Manage Certificates → ＋ → Apple Development
      3. 验证：
         security find-identity -v -p codesigning    # 应至少有 1 个身份
EOF
        ;;
      ios-team)
        cat <<EOF

  ${C_BOLD}($index) iOS：提供团队 ID（Team ID）${C_OFF}
      查法：Xcode 打开 ios/App/App.xcodeproj → 选中 App target → Signing & Capabilities
            → Team 右侧括号里的 10 位字符；或登录 developer.apple.com → Membership 查看。
      两种提供给脚本的方式（任选其一）：
        echo 'teamId=XXXXXXXXXX' > ios/signing.properties   # 本机私有，不入库
        IOS_TEAM_ID=XXXXXXXXXX npm run app:all
EOF
        ;;
      hap-toolchain)
        cat <<EOF

  ${C_BOLD}($index) HarmonyOS：安装 DevEco Studio${C_OFF}
      装好后默认路径即被识别；装在别处则指定：
        DEVECO_HOME=/path/to/DevEco-Studio.app/Contents npm run app:all
EOF
        ;;
      java)
        cat <<EOF

  ${C_BOLD}($index) HarmonyOS：安装 Java 运行时${C_OFF}
      鸿蒙打包阶段需要 Java（macOS 上 /usr/bin/java 只是空壳）：
        brew install openjdk@21
      装 DevEco Studio 的话，脚本也会优先用其自带的 JBR。
EOF
        ;;
      hap-project)
        cat <<EOF

  ${C_BOLD}($index) HarmonyOS：缺少 harmony/ 工程${C_OFF}
      本仓库自带该工程；若被删除，请从版本库恢复。
EOF
        ;;
      hap-signing)
        cat <<EOF

  ${C_BOLD}($index) HarmonyOS：配置签名（否则产物装不上设备）${C_OFF}
      1. DevEco Studio 打开 harmony/ 工程
      2. 菜单 File → Project Structure → Signing Configs
      3. 勾选「Automatically generate signature」（需登录华为开发者账号），确认后签名材料
         会自动写入 harmony/build-profile.json5（材料文件本身不入库）
      4. 重新执行：npm run app:all --only hap
EOF
        ;;
    esac
  done
  echo
}

# ── 构建 ─────────────────────────────────────────────────────────────
# 注意：macOS 自带的是 bash 3.2，没有关联数组（declare -A），故用「按平台前缀的普通变量」+
# 间接展开来记录结果（printf -v / ${!var} 在 3.2 上均可用）。
R_STATUS_android=''; R_ARTIFACT_android=''; R_DETAIL_android=''
R_STATUS_ios='';     R_ARTIFACT_ios='';     R_DETAIL_ios=''
R_STATUS_hap='';     R_ARTIFACT_hap='';     R_DETAIL_hap=''

set_result() {
  local platform="$1" status="$2" artifact="$3" detail="$4"
  printf -v "R_STATUS_$platform" '%s' "$status"
  printf -v "R_ARTIFACT_$platform" '%s' "$artifact"
  printf -v "R_DETAIL_$platform" '%s' "$detail"
}

build_android() {
  if [[ "$PRE_ANDROID_HARD" != true ]]; then
    set_result android skipped '' '缺 JDK / Android SDK'
    return 0
  fi
  info "执行 scripts/build-apk.sh（首次可能较慢：Gradle 需拉依赖）"
  if ./scripts/build-apk.sh; then
    local apk="android/app/build/outputs/apk/release/app-release.apk"
    if [[ -f "$apk" ]]; then
      if [[ "$PRE_ANDROID_KEYSTORE" == true ]]; then
        set_result android ok "$apk" '发布签名'
      else
        set_result android ok "$apk" 'debug 签名（不可用于正式分发）'
      fi
    else
      set_result android failed '' "脚本成功但未找到产物 $apk"
    fi
  else
    set_result android failed '' '构建失败（见上方 Gradle 输出）'
  fi
}

build_ios() {
  if [[ "$PRE_IOS_HARD" != true ]]; then
    set_result ios skipped '' '缺 Apple 签名（见下方补充步骤）'
    return 0
  fi
  info "执行 scripts/build-ios.sh（导出方式 IOS_EXPORT_METHOD=${IOS_EXPORT_METHOD:-development}）"
  if ./scripts/build-ios.sh; then
    local ipa
    ipa="$(find build/ios/ipa -maxdepth 1 -name '*.ipa' 2>/dev/null | sort | tail -1)"
    if [[ -n "$ipa" ]]; then
      set_result ios ok "$ipa" "已签名（${IOS_EXPORT_METHOD:-development}）"
    else
      set_result ios failed '' '脚本成功但未找到 .ipa'
    fi
  else
    set_result ios failed '' '构建 / 导出失败（见上方 xcodebuild 输出）'
  fi
}

build_hap() {
  if [[ "$PRE_HAP_HARD" != true ]]; then
    set_result hap skipped '' '缺 DevEco / Java'
    return 0
  fi
  info "执行 scripts/build-hap.sh"
  if ./scripts/build-hap.sh; then
    local hap
    hap="$(find harmony/entry/build -name '*.hap' -type f 2>/dev/null | sort | tail -1)"
    if [[ -n "$hap" ]]; then
      case "$hap" in
        *unsigned*) set_result hap ok "$hap" '未签名（装不上设备）' ;;
        *) set_result hap ok "$hap" '已签名' ;;
      esac
    else
      set_result hap failed '' '脚本成功但未找到 .hap'
    fi
  else
    set_result hap failed '' '构建失败（见上方 hvigor 输出）'
  fi
}

platform_label() {
  case "$1" in
    android) echo "Android" ;;
    ios) echo "iOS" ;;
    hap) echo "HarmonyOS" ;;
  esac
}

# ── 主流程 ────────────────────────────────────────────────────────────
# 步骤编号：--check 只有 1 步（预检）；正常构建是 3 步（预检 / 构建 / 汇总）。
TOTAL_STEPS=3
if $CHECK_ONLY; then TOTAL_STEPS=1; fi

step "1/$TOTAL_STEPS" "预检"
if $SKIP_PREFLIGHT && ! $CHECK_ONLY; then
  info "已按 --skip-preflight 跳过；如需查看缺项请执行：./scripts/build-mobile.sh --check"
  PRE_ANDROID_HARD=true; PRE_IOS_HARD=true; PRE_HAP_HARD=true
else
  is_selected android && preflight_android
  is_selected ios && preflight_ios
  is_selected hap && preflight_hap
fi
print_gaps

if $CHECK_ONLY; then
  echo2 ""
  echo2 "${C_BOLD}预检完成（未构建）。${C_OFF}去掉 --check 即开始构建：./scripts/build-mobile.sh"
  if [[ ${#GAPS[@]} -gt 0 ]]; then exit 1; fi
  exit 0
fi

step "2/$TOTAL_STEPS" "构建"
idx=1
for p in "${SELECTED[@]}"; do
  echo2 ""
  echo2 "${C_DIM}── ${idx}/${#SELECTED[@]}  ${C_OFF}${C_BOLD}$(platform_label "$p")${C_OFF}"
  "build_$p"
  idx=$((idx + 1))
done

step "3/$TOTAL_STEPS" "汇总"
FAILED=0
for p in "${SELECTED[@]}"; do
  label="$(platform_label "$p")"
  status_var="R_STATUS_$p"; detail_var="R_DETAIL_$p"; artifact_var="R_ARTIFACT_$p"
  status="${!status_var:-failed}"
  detail="${!detail_var:-}"
  artifact="${!artifact_var:-}"
  case "$status" in
    ok)
      size="$(du -h "$artifact" 2>/dev/null | cut -f1)"
      if [[ "$artifact" == *unsigned* || "$detail" == *debug* ]]; then
        warn "$label" "${artifact}（${size}）· ${detail}"
      else
        ok "$label" "${artifact}（${size}）· ${detail}"
      fi
      ;;
    skipped)
      bad "$label" "已跳过：${detail}"
      FAILED=1
      ;;
    *)
      bad "$label" "${detail}"
      FAILED=1
      ;;
  esac
done

echo2 ""
info "提醒：三端外壳都是直接加载线上站点（server.url），前端改动需先部署才会在 App 里生效："
info "      docker compose up -d --build frontend"
info "      Android 另有原生改动（EdgeToEdge），需重新安装本次产出的 APK。"

if [[ ${#GAPS[@]} -gt 0 ]]; then
  echo2 ""
  info "还有 ${#GAPS[@]} 项待补充（见上面「需要你补充」；可随时 ./scripts/build-mobile.sh --check 复查）"
fi

exit "$FAILED"
