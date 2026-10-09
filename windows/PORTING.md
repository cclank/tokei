# 从 Mac 版移植到 Windows 版的规范

Windows 版（`windows/`，Tauri 2 + React-TS）是 Mac 版（`Tokei/Sources/Tokei/*.swift`，SwiftUI）的忠实移植：
同样的布局、文案、配色、交互和数据口径。Mac 版代码是唯一的参照，改了 Mac 的界面，这里跟着改。

## 先读这些

- 数据与工具：`src/lib/`（`types.ts` 共用类型、`i18n.ts` 的 `L()`/`data()`、`fmt.ts` 对应 Swift `Fmt`、
  `store.tsx` 刷新与区间名、`collector.ts` 跑采集脚本、`native.ts` Rust 命令、`prefs.ts` 偏好、
  `trayQuota.ts` 托盘额度来源、`quotaHistory.ts` 额度曲线的记录、`share.tsx` 复制用量图）。
- 界面部件：`src/ui/`（`kit.tsx`、`models.tsx`、`theme.ts`、`Icon.tsx`），对应 `Design.swift` 与 `PanelView`
  的复用片段（CardHead、CostHeadline、MetricGrid、QuotaRow、ModelDisclosure……）。
- 卡片：`src/cards/`，每个文件导出 `CardSpec`，`registry.ts` 按 Mac 版 `PanelView.toolCards` 的顺序排。

## 规则

1. **文案**：用 `L("中文原文")`，key 必须与 Swift 里 `L(...)` 的中文原文**逐字一致**（含标点、空格），
   这样会直接用上 `Tokei/Localization/*.lproj` 的现成译文。采集器给的中文（窗口名、明细标签等）显示时
   用 `data(text)` 翻译。Windows 独有的句子照样加进四份词表。
2. **JSON 字段名**：Swift 的 `CodingKeys` 常把驼峰映射成下划线（`reserveQuota` ↔ `reserve_quota`）。
   定义 TS 类型前先看 `Model.swift` 的 `CodingKeys`，再用真实的 `~/.tokei/last_usage.json` 核对。
3. **字号与颜色**：Swift 的 `Theme.fontSize(x)` 写 `fs(x)`；`Theme.xxx` 用 `ui/theme.ts` 的同名常量，
   `tint.opacity(a)` 写 `rgba(tint, a)`，`Theme.tPrimary/tSecondary/tTertiary` 写 `T.primary/...`。
4. **图标**：SF Symbols 名字直接传给 `<Icon name="..." />`，没有的在 `Icon.tsx` 里补一条 lucide 映射。
5. **偏好键**：与 Mac 版 `@AppStorage` 同名（`showClaude`、`panelFontSize`……），默认值也一样。
6. **平台差异**：Mac 独有的能力（钥匙串授权、菜单栏文字、原生 Swift 助手等）在 Windows 上能等价实现就实现，
   做不了就不显示，并在 README 的「与 Mac 版的差异」里记一笔。
7. **校验**：`npx tsc --noEmit -p .` 和 `node scripts/check-i18n.mjs`（`pnpm build` 也会跑）。文案检查要求
   key 在英文词表里逐字存在、参数个数与占位符一致、中文都包在 `L()` 里；刻意保留的中文（数据标识等）
   在那一行写 `// l10n-ignore`。`TOKEI_EN_STRINGS` 可以指向另一份英文词表来对照。
