#!/usr/bin/env bash
# Tokei Collector — 远程设备一键部署
# 用法: curl -sL <url>/install.sh | bash -s -- --repo <git-repo-url> --name <device-name>
set -e

REPO=""
NAME=""
INTERVAL=30
SCRIPT_URL=""

while [[ $# -gt 0 ]]; do
    case $1 in
        --repo) REPO="$2"; shift 2 ;;
        --name) NAME="$2"; shift 2 ;;
        --interval) INTERVAL="$2"; shift 2 ;;
        *) echo "未知参数: $1"; exit 1 ;;
    esac
done

if ! [[ "$INTERVAL" =~ ^[0-9]+$ ]] || [ "$INTERVAL" -lt 1 ] || [ "$INTERVAL" -gt 59 ]; then
    echo "同步间隔必须是 1 到 59 分钟" >&2
    exit 1
fi

if [ -z "$REPO" ]; then
    echo "用法: install.sh --repo <git-repo-url> --name <device-name>"
    echo "  --repo      同步 Git 仓库地址(必填)"
    echo "  --name      设备名(默认: hostname)"
    echo "  --interval  同步间隔分钟(默认: 30)"
    exit 1
fi

[ -z "$NAME" ] && NAME=$(hostname -s)

echo "=== Tokei Collector 安装 ==="
echo "  仓库: $REPO"
echo "  设备: $NAME"
echo "  间隔: ${INTERVAL}m"
echo ""

# 1. 创建目录
TOKEI_DIR="$HOME/.tokei"
SYNC_DIR="$TOKEI_DIR/sync"
mkdir -p "$TOKEI_DIR"

# 2. 克隆同步仓库
if [ -d "$SYNC_DIR/.git" ]; then
    echo "[✓] 同步仓库已存在"
    cd "$SYNC_DIR" && git pull -q
else
    echo "[·] 克隆同步仓库..."
    git clone "$REPO" "$SYNC_DIR"
fi

# 3. 下载采集脚本和价格文件
SCRIPT="$TOKEI_DIR/usage.30s.py"
for fname in usage.30s.py pricing.json pricing_overrides.json; do
    dst="$TOKEI_DIR/$fname"
    if [ -f "$dst" ]; then
        echo "[✓] $fname 已存在"
    elif [ -f "$SYNC_DIR/$fname" ]; then
        cp "$SYNC_DIR/$fname" "$dst"
        echo "[✓] $fname 从同步仓库复制"
    elif [ -f "$(dirname "$0")/$fname" ]; then
        cp "$(dirname "$0")/$fname" "$dst"
        echo "[✓] $fname 从本地复制"
    else
        echo "[!] 请手动复制 $fname 到 $dst"
    fi
done

# 4. 确保 zstandard 可导入：OpenClaw 新版把事件正文压缩进 event_zstd，
#    缺依赖会静默跳过这部分用量。已装则跳过，装不上不阻断安装。
if python3 -c 'import zstandard' >/dev/null 2>&1; then
    echo "[✓] zstandard 已可用"
else
    echo "[·] 安装 zstandard（读 OpenClaw 压缩事件正文）..."
    if python3 -m pip install --quiet zstandard >/dev/null 2>&1 \
            || python3 -m pip install --quiet --user zstandard >/dev/null 2>&1 \
            || python3 -m pip install --quiet --break-system-packages zstandard >/dev/null 2>&1; then
        echo "[✓] zstandard 安装完成"
    else
        echo "[!] zstandard 未安装：OpenClaw 压缩存储的用量事件将被跳过"
        echo "    可手动执行: python3 -m pip install --user zstandard"
    fi
fi

# 5. 写配置
python3 - "$SYNC_DIR" "$NAME" "$INTERVAL" > "$TOKEI_DIR/config.json" <<'PY'
import json
import sys

json.dump({
    "sync_dir": sys.argv[1],
    "device_id": sys.argv[2],
    "auto_sync": True,
    "sync_interval": int(sys.argv[3]),
}, sys.stdout, ensure_ascii=False, indent=2)
print()
PY
echo "[✓] 配置已写入 $TOKEI_DIR/config.json"

# 6. 创建同步脚本
SYNC_SCRIPT="$TOKEI_DIR/sync.sh"
cat > "$SYNC_SCRIPT" <<'SYNCEOF'
#!/usr/bin/env bash
cd "$HOME/.tokei/sync" || exit 1
TOKEI="$HOME/.tokei"
PYTHONPATH="$TOKEI" python3 "$TOKEI/usage.30s.py" --json >/dev/null 2>&1
git pull -q --rebase --autostash 2>/dev/null
git add -A
git diff --cached --quiet || git commit -qm "tokei sync $(cat $HOME/.tokei/config.json | python3 -c 'import sys,json;print(json.load(sys.stdin).get("device_id","unknown"))' 2>/dev/null || echo unknown)"
git push -q 2>/dev/null
SYNCEOF
chmod +x "$SYNC_SCRIPT"
echo "[✓] 同步脚本: $SYNC_SCRIPT"

# 7. 添加 crontab
CRON_LINE="*/$INTERVAL * * * * $SYNC_SCRIPT >/dev/null 2>&1"
(crontab -l 2>/dev/null | grep -v "tokei/sync.sh"; echo "$CRON_LINE") | crontab -
echo "[✓] Cron 已配置: 每 ${INTERVAL} 分钟同步"

echo ""
echo "=== 安装完成 ==="
echo "  首次同步: bash $SYNC_SCRIPT"
echo "  查看状态: cat $SYNC_DIR/$NAME.json | python3 -m json.tool | head -5"
echo ""

# 8. 立即执行一次
bash "$SYNC_SCRIPT" && echo "[✓] 首次同步成功" || echo "[!] 首次同步失败,请检查 Git 权限"
