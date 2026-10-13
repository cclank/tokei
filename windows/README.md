# Tokei for Windows

Tokei 的 Windows 版：桌面窗口 + 系统托盘，用 [Tauri 2](https://tauri.app)（Rust + WebView2）实现，
界面是 React + TypeScript。用量数据仍由仓库根目录的 `usage.30s.py` 采集，安装包里带一份内嵌 Python，
用户不需要自己装。

## 功能

- 主窗口：手动启动即显示，带系统标题栏、最小化 / 最大化按钮和任务栏入口；可以拖动、调整大小。切换其他应用时保持打开。
- 快捷面板：独立的无边框用量面板，靠近托盘图标显示，失焦或按 Esc 收起；可以按原有时间范围查看卡片、复制用量图，并打开主窗口继续查看。
- 托盘：左键默认开合快捷面板；设置 → 界面 → 点击托盘图标，可切换为打开主窗口。右键菜单始终提供主窗口、快捷面板、刷新、设置和退出入口。
- 窗口关闭后继续在托盘运行；选择「退出」结束应用。登录时启动默认留在托盘。
- 页面：与 Mac 版同样的卡片、页签、项目足迹、额度曲线、数据面板（含回顾）、设置，复制整页或单个工具的用量图。窄窗口自动使用单列，导航和页脚保持可见。
- 界面语言跟随 Mac 版的词表（中、英、法、日、韩）。
- Provider 的 API Key 存在 Windows「凭据管理器」，采集时以环境变量交给脚本，不写进 `~/.tokei/config.json`。
- 防休眠（`SetThreadExecutionState`）。
- 主窗口统一采集并记录历史，快捷面板订阅带版本号的用量状态；两套窗口共用语言、字号和显示卡片偏好。
- 隐私与额度：应用活跃统计默认开启，每次启动仅尝试上报一次，可关闭并终止在途请求；Claude Code CLI 额度查询默认关闭，优先使用 Desktop 缓存，CLI 结果缓存 5 分钟。
- Grok Bot 授权：先开启额度查询，再点「授权 Grok Bot」，读取 Grok Bot 自身登录态；授权绑定当前账号，重启和升级后保留，切换账号后需重新授权。Token 不写入 Tokei 文件或传给页面。

## 与 Mac 版的差异

- 托盘图标画不了文字，Mac 菜单栏上的额度数字改成托盘悬停提示。
- 还没有：多设备同步、自动更新、久坐提醒。
- Windows 的 Grok Bot 授权使用当前用户的 DPAPI，以及 Electron 的加密数据；授权确认在 Tokei 内完成。Mac 使用钥匙串授权。Windows 授权只用于 Grok Bot 自身账号，不借用 Cursor 登录态。
- 已支持 DPAPI 和 Electron v10/v11 AES-GCM 数据。遇到应用绑定加密格式时会停止读取并提示，不尝试绕过其保护。
- 尚未提供 Zed 的授权界面。
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

- `native_bridge.py`：Windows 凭据解密、Grok Bot 授权与官方查询、Claude CLI 查询缓存、应用活跃统计。随安装包放在 `collector/windows_native.py`，使用内嵌 Python 和 cryptography。
- `src-tauri/src/`：双窗口与托盘（`panel.rs`）、工作区定位（`placement.rs`）、共享用量状态（`snapshot.rs`）、隐私进程控制（`privacy.rs`）、采集脚本（`collector.rs`）、防休眠（`power.rs`）、
  `~/.tokei` 文件与凭据管理器（`store.rs`）。
- `src/cards/`：各工具卡片，顺序见 `registry.ts`，与 Mac 版 `PanelView.toolCards` 一致。
- `src/pages/`：设置、数据面板、项目足迹、额度曲线。
- `src/ui/`：卡片部件（对应 Mac 版 `Design.swift` 与 `PanelView` 的复用片段）。
- `src/lib/`：数据刷新、文案、格式化、托盘、额度曲线记录、用量图。

从 Mac 版移植界面的约定见 [PORTING.md](PORTING.md)。

原生窗口的本机测试可使用 debug 构建的 `TOKEI_TEST_STATE_DIR` 指向独立绝对路径，并用 `TOKEI_SCRIPT` 指向固定采集样本；release 构建始终使用正常用户目录。托盘点击偏好保存在 `~/.tokei/windows-ui.json`。
### 启动加载

界面先显示导航和加载状态，配置同步完成后才开始采集和处理活跃统计开关。首次启动先用 `--local-only` 读取本地用量，再进行完整额度刷新；快捷面板首次打开时创建，并订阅主窗口的数据。

再次启动会先显示当天的用量预览，并标注原采集时间。预览文件 `~/.tokei/windows-usage-preview.json` 只保留用量区间，不保存账号、登录凭据或旧额度；损坏、过期和跨日的预览会被忽略。预览不写入额度历史。

设置、项目、数据面板、分享和语言词表按需加载。`pnpm build` 会检查首屏全部依赖的 JS 体积：中文 400 KiB、英文 450 KiB、其他支持语言 500 KiB。运行 `python -m unittest tests.test_windows_startup tests.test_windows_usage_snapshot -v` 可验证配置顺序、网络隔离和缓存覆盖顺序。Windows 实机的冷启动耗时仍需单独测量。
