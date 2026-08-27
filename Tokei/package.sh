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

swift build -c release

APP="Tokei.app"
BIN="$(swift build -c release --show-bin-path)/Tokei"
PROJ_DIR="$(dirname "$(pwd)")"

rm -rf "$APP"
mkdir -p "$APP/Contents/MacOS" "$APP/Contents/Resources"

# 二进制
cp "$BIN" "$APP/Contents/MacOS/Tokei"

# 打包 Python 脚本和配置到 Resources
cp "$PROJ_DIR/usage.30s.py" "$APP/Contents/Resources/"
[ -f "$PROJ_DIR/pricing.json" ] && cp "$PROJ_DIR/pricing.json" "$APP/Contents/Resources/"
[ -f "$PROJ_DIR/pricing_overrides.json" ] && cp "$PROJ_DIR/pricing_overrides.json" "$APP/Contents/Resources/"
[ -f "AppIcon.icns" ] && cp "AppIcon.icns" "$APP/Contents/Resources/"
[ -d "Sources/Tokei/Resources/sit" ] && cp -R "Sources/Tokei/Resources/sit" "$APP/Contents/Resources/"
[ -f "Sources/Tokei/Resources/github-mark.png" ] && cp "Sources/Tokei/Resources/github-mark.png" "$APP/Contents/Resources/"

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
    <key>CFBundlePackageType</key><string>APPL</string>
    <key>CFBundleExecutable</key><string>Tokei</string>
    <key>CFBundleIconFile</key><string>AppIcon</string>
    <key>LSMinimumSystemVersion</key><string>13.0</string>
    <key>LSUIElement</key><true/>
    <key>NSHighResolutionCapable</key><true/>
</dict>
</plist>
PLIST

codesign --force --deep --sign - "$APP"
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
    DEVICE=$(hdiutil attach -readwrite -noverify "$TMP_DMG" | grep '/Volumes/Tokei' | awk '{print $1}')
    sleep 1

    # 隐藏 dot 文件夹
    SetFile -a V /Volumes/Tokei/.background 2>/dev/null || true
    SetFile -a V /Volumes/Tokei/.fseventsd 2>/dev/null || true

    if [ -f "/Volumes/Tokei/.background/bg.png" ]; then
        osascript <<'APPLE'
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
    hdiutil detach "$DEVICE" 2>/dev/null
    sleep 1

    # 转为压缩只读 DMG
    hdiutil convert "$TMP_DMG" -format UDZO -o "$DMG" 2>/dev/null
    rm -f "$TMP_DMG"
    echo "DMG: $(pwd)/$DMG"

    /bin/bash generate_update_metadata.sh "$VERSION" "$DMG" latest.json
    echo "Update metadata: $(pwd)/latest.json"
fi
