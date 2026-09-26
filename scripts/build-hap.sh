#!/usr/bin/env bash
#
# 构建「艾欧泽亚放置录」HarmonyOS 安装包（.hap）。
#
#   ./scripts/build-hap.sh
#   ./scripts/build-hap.sh assembleHap --mode module -p product=default -p buildMode=debug
#
# 与 Android / iOS 不同，鸿蒙没有 Capacitor 支持，外壳是手写的 ArkTS 工程（harmony/），
# 同样只加载线上地址 —— 所以前端改动只需部署，不必重出 HAP。
#
# 前置条件：
#   1. 安装 DevEco Studio（本脚本默认用其自带的 hvigor / SDK / Node，可用环境变量覆盖）；
#   2. **签名**：HAP 必须签名才能安装到设备。签名材料（.p12 / .cer / .p7b）不入库，
#      请在 DevEco 里打开本工程后点「自动签名」（需登录华为开发者账号），
#      或手动填写 harmony/build-profile.json5 的 signingConfigs。
#      未配置签名时仍会产出 unsigned HAP —— 那只是编译验证产物，装不上设备。
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

DEVECO_HOME="${DEVECO_HOME:-/Applications/DevEco-Studio.app/Contents}"
HVIGORW="${HVIGORW:-$DEVECO_HOME/tools/hvigor/bin/hvigorw}"
SDK_HOME="${DEVECO_SDK_HOME:-$DEVECO_HOME/sdk}"
PROJECT_DIR="$ROOT/harmony"
APP_JSON="$PROJECT_DIR/AppScope/app.json5"

log() { printf '\033[36m[build-hap]\033[0m %s\n' "$*"; }
die() { printf '\033[31m[build-hap] %s\033[0m\n' "$*" >&2; exit 1; }

# ── 工具链自检 ────────────────────────────────────────────────────────
[[ -x "$HVIGORW" ]] || die "找不到 hvigorw（${HVIGORW}）。
     请安装 DevEco Studio，或用 DEVECO_HOME 指向其安装目录（Contents 一级）。"
[[ -d "$SDK_HOME" ]] || die "找不到 DevEco SDK（${SDK_HOME}）。可用 DEVECO_SDK_HOME 指定。"
[[ -d "$PROJECT_DIR" ]] || die "缺少鸿蒙工程 $PROJECT_DIR"
[[ -f "$APP_JSON" ]] || die "缺少 $APP_JSON"
log "hvigor：$HVIGORW"
log "SDK：$SDK_HOME"

# ── 版本号：与 Android / iOS 同源，取根目录 package.json ──────────────
# versionName = 完整版本号；versionCode = major*10000 + minor*100 + patch，
# 与 android/app/build.gradle 的 versionCode、iOS 的 CURRENT_PROJECT_VERSION 规则一致。
VERSION="$(node -p "require('./package.json').version")"
IFS=. read -r V_MAJOR V_MINOR V_PATCH <<<"$VERSION"
BUILD_NUMBER="$(( V_MAJOR * 10000 + V_MINOR * 100 + V_PATCH ))"
log "版本：${VERSION}（versionCode ${BUILD_NUMBER}）"

VERSION="$VERSION" BUILD_NUMBER="$BUILD_NUMBER" python3 - "$APP_JSON" <<'PY'
import os, re, sys

path = sys.argv[1]
text = open(path, encoding='utf-8').read()
version = os.environ['VERSION']
build = os.environ['BUILD_NUMBER']

# 先确认字段存在（不能用「替换后是否变化」判断：版本号没变时替换结果本就与原文相同）。
if not re.search(r'"versionName"\s*:\s*"[^"]*"', text) or not re.search(r'"versionCode"\s*:\s*\d+', text):
    sys.exit(f'[build-hap] 未能在 {path} 中找到 versionName / versionCode')

updated = re.sub(r'("versionName"\s*:\s*)"[^"]*"', rf'\g<1>"{version}"', text, count=1)
updated = re.sub(r'("versionCode"\s*:\s*)\d+', rf'\g<1>{build}', updated, count=1)
open(path, 'w', encoding='utf-8').write(updated)
print(f'[build-hap] 已同步 AppScope/app.json5 → {version} / {build}')
PY

# ── Java 运行时 ───────────────────────────────────────────────────────
# PackageHap 阶段会调用 Java 程序（打包 / 签名工具）。macOS 上若没装过系统 JDK，
# /usr/bin/java 只是个会报「Unable to locate a Java Runtime」的壳，所以这里显式挑一份可用的。
# DevEco 自带的 JBR 与它自己的构建链版本最匹配，优先使用。
pick_java_home() {
  local candidates=()
  [[ -n "${JAVA_HOME:-}" ]] && candidates+=("$JAVA_HOME")
  candidates+=(
    "$DEVECO_HOME/jbr/Contents/Home"
    "/opt/homebrew/opt/openjdk@21/libexec/openjdk.jdk/Contents/Home"
    "/usr/local/opt/openjdk@21/libexec/openjdk.jdk/Contents/Home"
  )
  if [[ -x /usr/libexec/java_home ]]; then
    local from_helper
    from_helper="$(/usr/libexec/java_home 2>/dev/null || true)"
    [[ -n "$from_helper" ]] && candidates+=("$from_helper")
  fi
  local candidate
  for candidate in "${candidates[@]}"; do
    if [[ -x "$candidate/bin/java" ]]; then
      echo "$candidate"
      return 0
    fi
  done
  return 1
}

JAVA_HOME="$(pick_java_home || true)"
if [[ -z "$JAVA_HOME" ]]; then
  die "找不到可用的 Java 运行时（HarmonyOS 打包阶段需要）。
     装一份即可：brew install openjdk@21，或用 JAVA_HOME 指定。"
fi
export JAVA_HOME
export PATH="$JAVA_HOME/bin:$PATH"
log "Java：$JAVA_HOME"

# ── hvigor 运行环境 ───────────────────────────────────────────────────
export DEVECO_SDK_HOME="$SDK_HOME"
# hvigorw 需要 Node：优先用 DevEco 自带的（版本匹配），否则退回 PATH 里的 node。
if [[ -z "${NODE_HOME:-}" && -x "$DEVECO_HOME/tools/node/bin/node" ]]; then
  export NODE_HOME="$DEVECO_HOME/tools/node"
  log "Node：$NODE_HOME"
fi

# ── 构建 ─────────────────────────────────────────────────────────────
# 无参数时默认出 release HAP；有参数则原样透传给 hvigorw。
if [[ $# -eq 0 ]]; then
  set -- assembleHap --mode module -p product=default -p buildMode=release --no-daemon
fi

log "hvigorw $*"
(cd "$PROJECT_DIR" && "$HVIGORW" "$@")

HAP="$(find "$PROJECT_DIR/entry/build" -name '*.hap' -type f 2>/dev/null | sort | tail -1 || true)"
[[ -n "$HAP" ]] || die "未找到 HAP 产物，请检查上面的 hvigor 日志。"
log "完成：${HAP}（$(du -h "$HAP" | cut -f1)）"

case "$HAP" in
  *unsigned*)
    log "提示：这是**未签名**产物，只能用于编译验证，无法安装到设备。"
    log "     请在 DevEco Studio 打开 harmony/ 工程 → File → Project Structure → Signing Configs"
    log "     勾选「Automatically generate signature」（需登录华为开发者账号），再重新执行本脚本。"
    ;;
esac
