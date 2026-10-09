# Tokei for Windows

Tokei 的 Windows 版：托盘图标 + 弹出面板，用 [Tauri 2](https://tauri.app)（Rust + WebView2）实现，
界面是 React + TypeScript。用量数据仍由仓库根目录的 `usage.30s.py` 采集，安装包里带一份内嵌 Python。

## 开发

```bash
pnpm install
pnpm dev            # 只调界面：浏览器打开 http://localhost:1420，数据来自本机跑一遍 usage.30s.py
pnpm tauri dev      # 完整应用（托盘、面板、Rust 命令），macOS 上也能跑
```

## 打包

Windows 安装包由 GitHub Actions 构建（`.github/workflows/windows.yml`）：下载 Python embeddable 包放到
`src-tauri/python/`，装上 `zstandard`，再 `pnpm tauri build` 生成 NSIS 安装包。

## 结构

- `src-tauri/src/`：托盘与面板定位（`panel.rs`）、跑采集脚本（`collector.rs`）、防休眠（`power.rs`）、
  `~/.tokei` 文件与凭据管理器（`store.rs`）。
- `src/cards/`：各工具卡片，顺序见 `registry.ts`，与 Mac 版 `PanelView.toolCards` 一致。
- `src/ui/`：卡片部件（对应 Mac 版 `Design.swift` 与 `PanelView` 的复用片段）。
- `src/lib/i18n.ts`：界面文案直接读 Mac 版的 `Tokei/Localization/*.lproj/Localizable.strings`。
