# Tokei for Windows

Tokei 的 Windows 版：托盘图标 + 弹出面板，用 [Tauri 2](https://tauri.app)（Rust + WebView2）实现，
界面是 React + TypeScript。用量数据仍由仓库根目录的 `usage.30s.py` 采集，安装包里带一份内嵌 Python，
用户不需要自己装。

## 功能

- 托盘：左键开合面板，右键菜单有刷新、设置、登录时启动、退出；悬停提示列出「额度来源」里勾选的剩余额度。
- 面板：与 Mac 版同样的卡片、页签、项目足迹、额度曲线、数据面板（含回顾）、设置，复制整页或单个工具的用量图。
- 界面语言跟随 Mac 版的词表（中、英、法、日、韩）。
- Provider 的 API Key 存在 Windows「凭据管理器」，采集时以环境变量交给脚本，不写进 `~/.tokei/config.json`。
- 防休眠（`SetThreadExecutionState`）。

## 与 Mac 版的差异

- 托盘图标画不了文字，Mac 菜单栏上的额度数字改成托盘悬停提示。
- 还没有：多设备同步、自动更新、久坐提醒、应用活跃统计。
- 依赖 macOS 钥匙串助手的功能不显示：Claude Code CLI 额度查询、Grok Bot 授权、Zed 授权。
- 项目足迹：点一行在资源管理器里定位文件夹（Mac 是打开终端）；本机端口检测在 Windows 上暂无数据。

## 开发

```bash
pnpm install
pnpm dev            # 只调界面：浏览器打开 http://localhost:1420，数据来自本机跑一遍 usage.30s.py
pnpm tauri dev      # 完整应用（托盘、面板、Rust 命令），macOS 上也能跑
pnpm check:i18n     # 界面文案检查（pnpm build 也会跑）
```

浏览器里调界面时，`~/.tokei` 下的文件只读不写，Key、开机自启这些系统功能是空操作。

## 打包

Windows 安装包由 GitHub Actions 构建（`.github/workflows/windows.yml`）：下载 Python embeddable 包放到
`src-tauri/python/`，装上 `zstandard`，再 `pnpm tauri build` 生成 NSIS 安装包（暂未签名）。

## 结构

- `src-tauri/src/`：托盘与面板定位（`panel.rs`）、跑采集脚本（`collector.rs`）、防休眠（`power.rs`）、
  `~/.tokei` 文件与凭据管理器（`store.rs`）。
- `src/cards/`：各工具卡片，顺序见 `registry.ts`，与 Mac 版 `PanelView.toolCards` 一致。
- `src/pages/`：设置、数据面板、项目足迹、额度曲线。
- `src/ui/`：卡片部件（对应 Mac 版 `Design.swift` 与 `PanelView` 的复用片段）。
- `src/lib/`：数据刷新、文案、格式化、托盘、额度曲线记录、用量图。

从 Mac 版移植界面的约定见 [PORTING.md](PORTING.md)。
