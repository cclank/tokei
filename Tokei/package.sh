#!/bin/bash
# 构建并打包成 .app + .dmg(无需 Xcode,仅 SwiftPM)。
set -e
cd "$(dirname "$0")"

VERSION="$(sed -nE 's/.*releaseTag = "v([^"]+)".*/\1/p' Sources/Tokei/Updater.swift | head -n 1)"
if [[ ! "$VERSION" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
    echo "无法从 Updater.swift 读取版本号" >&2
    exit 1
fi

# 只记录本次打包日期，不把它混入正式版本号或 CFBundleVersion。
# 允许测试和可复现打包显式指定日期。
BUILD_DATE="${TOKEI_BUILD_DATE:-$(date '+%Y.%m.%d')}"
if [[ ! "$BUILD_DATE" =~ ^[0-9]{4}\.[0-9]{2}\.[0-9]{2}$ ]]; then
    echo "构建日期格式无效，应为 YYYY.MM.DD: $BUILD_DATE" >&2
    exit 1
fi

# 本地验证时显式设置 TOKEI_LOCAL_BUILD=1，避免更新到尚未包含本地修复的线上包。
case "${TOKEI_LOCAL_BUILD:-0}" in
    0) LOCAL_BUILD=false ;;
    1) LOCAL_BUILD=true ;;
    *) echo "TOKEI_LOCAL_BUILD 必须是 0 或 1" >&2; exit 1 ;;
esac

# Command Line Tools 27 的 SwiftUI SDK 会引用 SwiftUIMacros.StateMacro，
# 但部分 CLT 安装并未包含对应插件。此时使用同一工具链自带的 26.x SDK。
if [[ -z "${SDKROOT:-}" ]]; then
    DEVELOPER_PATH="$(xcode-select -p 2>/dev/null || true)"
    DEFAULT_SDK="$(xcrun --sdk macosx --show-sdk-path 2>/dev/null || true)"
    SWIFTUI_CORE_MODULES="$DEFAULT_SDK/System/Library/Frameworks/SwiftUICore.framework/Versions/A/Modules"
    SWIFTUI_MACROS_PLUGIN="$DEVELOPER_PATH/usr/lib/swift/host/plugins/libSwiftUIMacros.dylib"

    if [[ "$DEVELOPER_PATH" == */CommandLineTools ]] \
        && [[ -d "$SWIFTUI_CORE_MODULES" ]] \
        && grep -Rqs 'type: "StateMacro"' "$SWIFTUI_CORE_MODULES" \
        && [[ ! -f "$SWIFTUI_MACROS_PLUGIN" ]]; then
        COMPATIBLE_SDK="$DEVELOPER_PATH/SDKs/MacOSX26.sdk"
        if [[ ! -d "$COMPATIBLE_SDK" ]]; then
            echo "当前 Command Line Tools 缺少 SwiftUIMacros，请安装完整 Xcode 后重试" >&2
            exit 1
        fi
        export SDKROOT="$COMPATIBLE_SDK"
        echo "Command Line Tools 缺少 SwiftUIMacros，使用兼容 SDK: $SDKROOT"
    fi
fi

swift build -c release

APP="Tokei.app"
BIN="$(swift build -c release --show-bin-path)/Tokei"
GROK_BOT_HELPER="$(swift build -c release --show-bin-path)/TokeiGrokBotHelper"
PROJ_DIR="$(dirname "$(pwd)")"

rm -rf "$APP"
mkdir -p "$APP/Contents/MacOS" "$APP/Contents/Helpers" "$APP/Contents/Resources"

# 二进制
cp "$BIN" "$APP/Contents/MacOS/Tokei"
cp "$GROK_BOT_HELPER" "$APP/Contents/Helpers/TokeiGrokBotHelper"
chmod 755 "$APP/Contents/Helpers/TokeiGrokBotHelper"

# 打包 Python 脚本和配置到 Resources
cp "$PROJ_DIR/usage.30s.py" "$APP/Contents/Resources/"
[ -f "$PROJ_DIR/pricing.json" ] && cp "$PROJ_DIR/pricing.json" "$APP/Contents/Resources/"
[ -f "$PROJ_DIR/pricing_overrides.json" ] && cp "$PROJ_DIR/pricing_overrides.json" "$APP/Contents/Resources/"
[ -f "AppIcon.icns" ] && cp "AppIcon.icns" "$APP/Contents/Resources/"
[ -d "Sources/Tokei/Resources/sit" ] && cp -R "Sources/Tokei/Resources/sit" "$APP/Contents/Resources/"
[ -f "Sources/Tokei/Resources/github-mark.png" ] && cp "Sources/Tokei/Resources/github-mark.png" "$APP/Contents/Resources/"
# 本地化资源：SwiftPM 把 *.lproj 打进 Tokei_Tokei.bundle，拷到 App 包内供 NSLocalizedString 读取。
BUNDLE_DIR="$(swift build -c release --show-bin-path)/Tokei_Tokei.bundle"
if [ -d "$BUNDLE_DIR/Contents/Resources" ]; then
    for lang in en zh fr ja ko; do
        [ -d "$BUNDLE_DIR/Contents/Resources/$lang.lproj" ] \
            && cp -R "$BUNDLE_DIR/Contents/Resources/$lang.lproj" "$APP/Contents/Resources/"
    done
fi

# Info.plist
cat > "$APP/Contents/Info.plist" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>CFBundleName</key><string>Tokei</string>
    <key>CFBundleDisplayName</key><string>Tokei</string>
    <key>CFBundleIdentifier</key><string>com.tokei.app</string>
    <key>CFBundleVersion</key><string>${VERSION}</string>
    <key>CFBundleShortVersionString</key><string>${VERSION}</string>
    <key>TokeiBuildDate</key><string>${BUILD_DATE}</string>
    <key>TokeiLocalBuild</key><${LOCAL_BUILD}/>
    <key>CFBundlePackageType</key><string>APPL</string>
    <key>CFBundleExecutable</key><string>Tokei</string>
    <key>CFBundleIconFile</key><string>AppIcon</string>
    <key>CFBundleDevelopmentRegion</key><string>en</string>
    <key>CFBundleLocalizations</key><array><string>en</string><string>zh</string><string>fr</string><string>ja</string><string>ko</string></array>
    <key>LSMinimumSystemVersion</key><string>13.0</string>
    <key>LSUIElement</key><true/>
    <key>NSHighResolutionCapable</key><true/>
</dict>
</plist>
PLIST

# A stable local signing identity keeps macOS Keychain ACLs valid across
# rebuilds. Prefer Developer ID, then Apple Development; CI can force ad-hoc
# signing with TOKEI_CODESIGN_IDENTITY=-.
# 注意：自动探测只服务本地开发。release.sh 固定传 TOKEI_CODESIGN_IDENTITY=-,
# 发布产物不会带上构建机上的个人证书。
CODESIGN_IDENTITY="${TOKEI_CODESIGN_IDENTITY:-auto}"
if [ "$CODESIGN_IDENTITY" = "auto" ]; then
    CODESIGN_IDENTITY=""
    if command -v security &>/dev/null; then
        IDENTITIES="$(security find-identity -v -p codesigning 2>/dev/null || true)"
        CODESIGN_IDENTITY="$(echo "$IDENTITIES" \
            | sed -nE 's/^[[:space:]]*[0-9]+\) [0-9A-F]+ "(Developer ID Application:[^"]+)".*/\1/p' \
            | head -n 1)"
        if [ -z "$CODESIGN_IDENTITY" ]; then
            CODESIGN_IDENTITY="$(echo "$IDENTITIES" \
                | sed -nE 's/^[[:space:]]*[0-9]+\) [0-9A-F]+ "(Apple Development:[^"]+)".*/\1/p' \
                | head -n 1)"
        fi
    fi
    [ -n "$CODESIGN_IDENTITY" ] || CODESIGN_IDENTITY="-"
fi

if [ "$CODESIGN_IDENTITY" = "-" ]; then
    echo "未找到稳定签名证书，使用 ad-hoc 签名；后续重编译可能需要重新保存 Provider 密钥"
else
    echo "使用代码签名: $CODESIGN_IDENTITY"
fi
codesign --force --deep --sign "$CODESIGN_IDENTITY" "$APP"
codesign --verify --deep --strict "$APP"
xattr -cr "$APP" 2>/dev/null || true
echo "Built: $(pwd)/$APP"

# 打包 DMG（含自定义背景 + 图标布局）
if command -v hdiutil &>/dev/null; then
    DMG="Tokei.dmg"
    rm -f "$DMG"

    # 生成背景图
    BG_IMG="dmg_background.png"
    if [ ! -f "$BG_IMG" ] && command -v python3 &>/dev/null; then
        python3 dmg_bg.py 2>/dev/null || true
    fi

    TMP_DMG="/tmp/tokei_rw_$$.dmg"
    MOUNT_DIR="/tmp/tokei_mount_$$"

    # 创建可读写 DMG
    mkdir -p "$MOUNT_DIR"
    cp -R "$APP" "$MOUNT_DIR/"
    ln -s /Applications "$MOUNT_DIR/Applications"

    # 安装说明（可复制的 xattr 命令）
    cat > "$MOUNT_DIR/安装说明.txt" <<'INSTALL'
Tokei 安装说明
==============

1. 将 Tokei.app 拖入 Applications 文件夹

2. 首次打开如被 macOS 拦截，请在终端运行:

   sudo xattr -rd com.apple.quarantine /Applications/Tokei.app

3. 重新打开 Tokei.app 即可

更多信息: https://tokei.lanshuagent.com
INSTALL

    # 复制背景图到隐藏目录
    if [ -f "$BG_IMG" ]; then
        mkdir -p "$MOUNT_DIR/.background"
        cp "$BG_IMG" "$MOUNT_DIR/.background/bg.png"
    fi

    hdiutil create -volname "Tokei" -srcfolder "$MOUNT_DIR" -ov -format UDRW "$TMP_DMG" 2>/dev/null
    rm -rf "$MOUNT_DIR"

    # 挂载并用 AppleScript 设置窗口样式
    ATTACH_OUTPUT="$(hdiutil attach -readwrite -noverify "$TMP_DMG")"
    DEVICE="$(echo "$ATTACH_OUTPUT" | awk '/^\/dev\/disk/ {print $1; exit}')"
    VOLUME_PATH="$(echo "$ATTACH_OUTPUT" | sed -n 's|^.*\(/Volumes/.*\)$|\1|p' | head -n 1)"
    if [ -z "$DEVICE" ]; then
        echo "无法识别已挂载 DMG 的设备" >&2
        exit 1
    fi
    sleep 1

    # 新版 hdiutil 可能只附加设备而不返回 /Volumes 挂载点；窗口装饰是可选项。
    if [ -n "$VOLUME_PATH" ] && [ -d "$VOLUME_PATH" ]; then
        [ -d "$VOLUME_PATH/.background" ] \
            && SetFile -a V "$VOLUME_PATH/.background" 2>/dev/null || true
        [ -d "$VOLUME_PATH/.fseventsd" ] \
            && SetFile -a V "$VOLUME_PATH/.fseventsd" 2>/dev/null || true
    fi

    if [ -n "$VOLUME_PATH" ] && [ -f "$VOLUME_PATH/.background/bg.png" ]; then
        osascript <<'APPLE' || true
tell application "Finder"
    tell disk "Tokei"
        open
        set current view of container window to icon view
        set toolbar visible of container window to false
        set statusbar visible of container window to false
        set bounds of container window to {200, 120, 860, 520}
        set theViewOptions to icon view options of container window
        set arrangement of theViewOptions to not arranged
        set icon size of theViewOptions to 80
        set background picture of theViewOptions to file ".background:bg.png"
        set position of item "Tokei.app" of container window to {150, 175}
        set position of item "Applications" of container window to {510, 175}
        set position of item "安装说明.txt" of container window to {150, 310}
        close
        open
        delay 1
        close
    end tell
end tell
APPLE
    fi

    sync
    if command -v diskutil &>/dev/null; then
        EJECT_COMMAND=(diskutil eject "$DEVICE")
    else
        EJECT_COMMAND=(hdiutil detach "$DEVICE")
    fi
    EJECTED=0
    for _attempt in 1 2 3 4 5; do
        sleep 1
        if "${EJECT_COMMAND[@]}" >/dev/null 2>&1; then
            EJECTED=1
            break
        fi
    done
    if [ "$EJECTED" -ne 1 ]; then
        hdiutil detach -force "$DEVICE" 2>/dev/null
    fi
    sleep 1

    # 转为压缩只读 DMG
    hdiutil convert "$TMP_DMG" -format UDZO -o "$DMG" 2>/dev/null
    rm -f "$TMP_DMG"
    echo "DMG: $(pwd)/$DMG"

    /bin/bash generate_update_metadata.sh "$VERSION" "$DMG" latest.json
    echo "Update metadata: $(pwd)/latest.json"
fi
