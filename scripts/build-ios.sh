#!/usr/bin/env bash
#
# 构建「艾欧泽亚放置录」iOS 安装包（.ipa）。
#
#   ./scripts/build-ios.sh
#   IOS_EXPORT_METHOD=app-store-connect ./scripts/build-ios.sh
#   EORZEA_APP_URL=http://192.168.1.10:19999 ./scripts/build-ios.sh   # 临时指向别的地址
#
# 流程：生成前端产物 → cap sync 同步进 ios/ → xcodebuild archive → 导出 .ipa。
#
# 与 Android 不同，iOS 的产物**必须**由 Apple 签名，因此前置条件缺一不可（脚本会自检并给出提示）：
#   1. 完整安装的 Xcode（仅 Command Line Tools 不够）；
#   2. Xcode 里登录了 Apple ID（Xcode → Settings → Accounts）：付费开发者账号才能出
#      App Store / ad-hoc / 企业包；免费账号只能出 7 天有效的开发包，且需连真机安装；
#   3. 团队 ID：用 IOS_TEAM_ID 环境变量传入，或写进 ios/signing.properties（本机私有、不入库）。
#
# 导出方式由 IOS_EXPORT_METHOD 决定：
#   development（默认，真机调试） | ad-hoc（内部分发，需登记设备 UDID）
#   | app-store-connect（App Store / TestFlight） | enterprise（企业内部分发）
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

PROJECT="ios/App/App.xcodeproj"
SCHEME="App"
ARCHIVE="build/ios/App.xcarchive"
EXPORT_DIR="build/ios/ipa"
EXPORT_PLIST="build/ios/ExportOptions.plist"

log() { printf '\033[36m[build-ios]\033[0m %s\n' "$*"; }
die() { printf '\033[31m[build-ios] %s\033[0m\n' "$*" >&2; exit 1; }

# ── Xcode ─────────────────────────────────────────────────────────────
# 只用 Command Line Tools 时 xcode-select -p 指向 /Library/Developer/CommandLineTools，
# 那里没有 xcodebuild，也就无法 archive / 导出，故先把它和"没装 Xcode"区分开。
DEV_DIR="$(xcode-select -p 2>/dev/null || true)"
case "$DEV_DIR" in
  *Xcode*.app/Contents/Developer) ;;
  *)
    die "需要完整安装的 Xcode（当前 developer 目录：${DEV_DIR:-未设置}）。
     装好 Xcode 后执行：sudo xcode-select -s /Applications/Xcode.app/Contents/Developer
     然后在 Xcode → Settings → Accounts 登录 Apple ID。"
    ;;
esac
command -v xcodebuild >/dev/null 2>&1 || die "找不到 xcodebuild。"
log "Xcode：$(xcodebuild -version | head -1)"

[[ -d "$PROJECT" ]] || die "缺少 iOS 工程 ${PROJECT}（先执行：npx cap add ios）"

# ── 版本号：与 Android 同源，取根目录 package.json ────────────────────
# MARKETING_VERSION 取完整版本号，CURRENT_PROJECT_VERSION 取 major*10000+minor*100+patch，
# 与 android/app/build.gradle 的 versionName / versionCode 规则一致，避免两端口径漂移。
VERSION="$(node -p "require('./package.json').version")"
IFS=. read -r V_MAJOR V_MINOR V_PATCH <<<"$VERSION"
BUILD_NUMBER="$(( V_MAJOR * 10000 + V_MINOR * 100 + V_PATCH ))"
log "版本：${VERSION}（build ${BUILD_NUMBER}）"

# ── 签名团队 ──────────────────────────────────────────────────────────
TEAM="${IOS_TEAM_ID:-}"
if [[ -z "$TEAM" && -f ios/signing.properties ]]; then
  TEAM="$(sed -n 's/^teamId=//p' ios/signing.properties | head -1)"
fi
if [[ -n "$TEAM" ]]; then
  log "签名团队：$TEAM"
else
  log "未提供团队 ID（IOS_TEAM_ID 或 ios/signing.properties）——App Store / ad-hoc / 企业包必须提供，否则导出会失败。"
fi

# ── 导出方式 ──────────────────────────────────────────────────────────
METHOD="${IOS_EXPORT_METHOD:-development}"
case "$METHOD" in
  development | ad-hoc | app-store-connect | enterprise) ;;
  *) die "未知的 IOS_EXPORT_METHOD：${METHOD}（可选 development | ad-hoc | app-store-connect | enterprise）" ;;
esac

# ── 前端产物 + 同步 ───────────────────────────────────────────────────
log "构建前端产物…"
npm run --silent build

log "同步到 ios/…"
npx cap sync ios

# ── 归档 ─────────────────────────────────────────────────────────────
rm -rf "$ARCHIVE" "$EXPORT_DIR"
mkdir -p "$(dirname "$ARCHIVE")"

SIGN_ARGS=(MARKETING_VERSION="$VERSION" CURRENT_PROJECT_VERSION="$BUILD_NUMBER")
if [[ -n "$TEAM" ]]; then
  SIGN_ARGS+=(DEVELOPMENT_TEAM="$TEAM" CODE_SIGN_STYLE=Automatic)
fi

log "xcodebuild archive…"
xcodebuild \
  -project "$PROJECT" \
  -scheme "$SCHEME" \
  -configuration Release \
  -destination 'generic/platform=iOS' \
  -archivePath "$ARCHIVE" \
  "${SIGN_ARGS[@]}" \
  archive

[[ -d "$ARCHIVE" ]] || die "归档失败：未生成 $ARCHIVE"

# ── 导出 .ipa ────────────────────────────────────────────────────────
# ExportOptions 在构建时生成（而不是入库一份静态文件），避免把团队 ID 写进版本库。
{
  printf '<?xml version="1.0" encoding="UTF-8"?>\n'
  printf '<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">\n'
  printf '<plist version="1.0">\n<dict>\n'
  printf '  <key>method</key><string>%s</string>\n' "$METHOD"
  printf '  <key>signingStyle</key><string>automatic</string>\n'
  if [[ -n "$TEAM" ]]; then
    printf '  <key>teamID</key><string>%s</string>\n' "$TEAM"
  fi
  printf '  <key>stripSwiftSymbols</key><true/>\n'
  printf '  <key>compileBitcode</key><false/>\n'
  printf '</dict>\n</plist>\n'
} > "$EXPORT_PLIST"

log "xcodebuild -exportArchive（method=${METHOD}）…"
xcodebuild -exportArchive \
  -archivePath "$ARCHIVE" \
  -exportOptionsPlist "$EXPORT_PLIST" \
  -exportPath "$EXPORT_DIR"

IPA="$(find "$EXPORT_DIR" -maxdepth 1 -name '*.ipa' 2>/dev/null | head -1 || true)"
if [[ -z "$IPA" ]]; then
  die "导出失败：$EXPORT_DIR 下没有 .ipa。
     常见原因：Xcode 未登录 Apple ID；账号没有该导出方式所需的证书 / 描述文件；
     ad-hoc 未登记设备 UDID。可在 Xcode 打开 ios/App/App.xcodeproj 用图形界面排查。"
fi
log "完成：${IPA}（$(du -h "$IPA" | cut -f1)）"

# 顺带打印签名信息，确认用的是发布证书而不是开发证书。
if command -v codesign >/dev/null 2>&1; then
  APP="$(mktemp -d)/payload"
  mkdir -p "$APP"
  if unzip -qq "$IPA" -d "$APP" 2>/dev/null; then
    codesign -dv --verbose=2 "$APP/Payload/App.app" 2>&1 | sed -n 's/^\(Authority\|TeamIdentifier\)=/\1: /p' | head -4 || true
  fi
  rm -rf "$APP"
fi
