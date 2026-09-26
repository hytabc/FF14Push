#!/usr/bin/env bash
#
# 构建「艾欧泽亚放置录」Android 安装包（release，已签名）。
#
#   ./scripts/build-apk.sh
#   EORZEA_APP_URL=http://192.168.1.10:19999 ./scripts/build-apk.sh   # 临时指向别的地址
#
# 流程：生成前端产物 → cap sync 同步进 android/ → Gradle 打 release APK。
# JDK 与 Android SDK 会自动探测（JAVA_HOME / Android Studio 自带 JDK、ANDROID_HOME / 默认 SDK 目录），
# 因此无需先在 shell 里 export。签名配置见 android/keystore.properties（缺失则回退 debug 签名）。
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

log() { printf '\033[36m[build-apk]\033[0m %s\n' "$*"; }
die() { printf '\033[31m[build-apk] %s\033[0m\n' "$*" >&2; exit 1; }

# ── JDK ───────────────────────────────────────────────────────────────
# 需要「完整」的 JDK 21–24，两个条件都不能少：
#   1. 版本：Gradle 8.14.3 自带的 Groovy 3 读不懂 JDK 25 的 class 文件
#      （Unsupported class file major version 69），会直接构建失败；
#   2. 完整性：AGP 要用 jlink 把 core-for-system-modules.jar 转成编译用的系统镜像，
#      而 JetBrains 的 JBR（Android Studio / IDEA / PyCharm 自带）是精简运行时，没有 jlink。
# 所以这里逐个候选检查「版本合适且带 jlink」，而不是"有 java 就用"。
JDK_MIN=21
JDK_MAX=24

jdk_major() {
  "$1/bin/java" -version 2>&1 | sed -n '1s/.*version "\([0-9]*\).*/\1/p'
}

pick_jdk() {
  local candidates=()
  [[ -n "${JAVA_HOME:-}" ]] && candidates+=("$JAVA_HOME")
  candidates+=(
    "/opt/homebrew/opt/openjdk@21/libexec/openjdk.jdk/Contents/Home"
    "/usr/local/opt/openjdk@21/libexec/openjdk.jdk/Contents/Home"
    "/Library/Java/JavaVirtualMachines/temurin-21.jdk/Contents/Home"
    "/Applications/Android Studio.app/Contents/jbr/Contents/Home"
    "/Applications/IntelliJ IDEA.app/Contents/jbr/Contents/Home"
    "/Applications/PyCharm.app/Contents/jbr/Contents/Home"
  )
  if [[ -x /usr/libexec/java_home ]]; then
    local h
    h="$(/usr/libexec/java_home -v 21 2>/dev/null || true)"
    [[ -n "$h" ]] && candidates+=("$h")
  fi

  local candidate major
  for candidate in "${candidates[@]}"; do
    [[ -x "$candidate/bin/java" && -x "$candidate/bin/jlink" ]] || continue
    major="$(jdk_major "$candidate")"
    [[ -n "$major" ]] || continue
    if (( major >= JDK_MIN && major <= JDK_MAX )); then
      echo "$candidate"
      return 0
    fi
  done
  return 1
}

JAVA_HOME="$(pick_jdk || true)"
if [[ -z "$JAVA_HOME" ]]; then
  die "找不到完整可用的 JDK ${JDK_MIN}–${JDK_MAX}（需要自带 jlink）。安装一份即可：brew install openjdk@21"
fi
export JAVA_HOME
log "JDK: ${JAVA_HOME}（$(jdk_major "$JAVA_HOME")）"

# ── Android SDK ───────────────────────────────────────────────────────
SDK="${ANDROID_HOME:-${ANDROID_SDK_ROOT:-}}"
if [[ -z "$SDK" ]]; then
  for candidate in "$HOME/Library/Android/sdk" "$HOME/Android/Sdk"; do
    [[ -d "$candidate" ]] && SDK="$candidate" && break
  done
fi
[[ -n "$SDK" && -d "$SDK" ]] || die "找不到 Android SDK。请安装 Android Studio / SDK，或先 export ANDROID_HOME。"
export ANDROID_HOME="$SDK"
export ANDROID_SDK_ROOT="$SDK"
log "Android SDK: $SDK"

# Gradle 需要一个 local.properties 指明 SDK 位置（该文件不入库）。
if [[ ! -f android/local.properties ]]; then
  printf 'sdk.dir=%s\n' "$SDK" > android/local.properties
  log "已写入 android/local.properties"
fi

# ── 前端产物 + 同步 ───────────────────────────────────────────────────
log "构建前端产物…"
npm run --silent build

log "同步到 android/…"
npx cap sync android

# ── 打包 ─────────────────────────────────────────────────────────────
log "Gradle assembleRelease…"
(cd android && ./gradlew --no-daemon assembleRelease)

APK="android/app/build/outputs/apk/release/app-release.apk"
[[ -f "$APK" ]] || die "未找到产物 $APK"
log "完成：${APK}（$(du -h "$APK" | cut -f1)）"

# 顺带打印签名信息，方便确认用的是发布密钥而不是 debug 密钥。
if command -v apksigner >/dev/null 2>&1; then
  apksigner verify --print-certs "$APK" | head -5
elif [[ -x "$SDK/build-tools/$(ls "$SDK/build-tools" | sort -V | tail -1)/apksigner" ]]; then
  "$SDK/build-tools/$(ls "$SDK/build-tools" | sort -V | tail -1)/apksigner" verify --print-certs "$APK" | head -5
fi
