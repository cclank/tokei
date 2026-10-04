# Codex 重置卡 PR 截图

离屏渲染（与 `Tokei --shot` 一致），不依赖真实 Codex 登录态。

## 生成 PR 截图

构建本地 App 并生成折叠与展开状态截图：

```bash
cd Tokei
TOKEI_ARCHS=arm64 TOKEI_LOCAL_BUILD=1 ./package.sh

# 折叠状态
./Tokei.app/Contents/MacOS/Tokei \
  --lang zh \
  --usage ../docs/pr-codex-reset/usage-reset-cards.json \
  --shot ../docs/pr-codex-reset/codex-reset-collapsed.png

# 展开状态
./Tokei.app/Contents/MacOS/Tokei \
  --lang zh \
  --usage ../docs/pr-codex-reset/usage-reset-cards.json \
  --expand-codex-reset-cards \
  --shot ../docs/pr-codex-reset/codex-reset-expanded.png
```

## 交互式预览

若需要在真实 macOS 状态栏弹窗中查看效果（只读 fixture，不启动采集、同步、更新或活动上报）：

```bash
./Tokei/Tokei.app/Contents/MacOS/Tokei \
  --preview-usage \
  --usage docs/pr-codex-reset/usage-reset-cards.json \
  --expand-codex-reset-cards
```

## 技术说明

- `usage-reset-cards.json` 里的 `expires` 为相对时间戳；重置卡倒计时基于当前系统时间动态计算。
- SwiftUI `ImageRenderer` 离屏渲染不支持 `NSViewRepresentable`，否则会退化为 macOS 黄底红禁行占位符。`VisualEffect.isOffscreen` 在 `--shot` 模式下自动跳过毛玻璃层与 tooltip 桥接视图，保证所有 SF Symbols 与界面元素正常绘制。
