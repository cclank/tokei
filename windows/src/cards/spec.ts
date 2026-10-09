// 一张工具卡片的登记信息（Mac 版 PanelView.ToolCardItem）。
// 每个卡片文件导出自己的 CardSpec，registry.ts 按 Mac 版的顺序排起来。
import type { ReactNode } from "react";
import type { RangeKey, Usage } from "../lib/types";
import type { RGB } from "../ui/theme";

export interface CardContext {
  usage: Usage;
  /** 当前页签。 */
  range: RangeKey;
  /** 当前页签的显示名（「今日」「本周」…，已翻译）。 */
  rangeLabel: string;
  /** 正在刷新：空态要能分辨「刷新中」和「真的没有」。 */
  refreshing: boolean;
  /** 读界面偏好（与 Mac 版 @AppStorage 同名的键）。 */
  pref: <T>(key: string, fallback: T) => T;
}

export interface CardSpec {
  /** 与 Mac 版一致的工具 id（claude、codex、grok-bot、qodercli_cn …）。 */
  id: string;
  /** 「未检测到本地数据」一行里的名字。 */
  name: string | (() => string);
  /** 显示开关在偏好里的键与默认值（Mac 版 showClaude 等）。 */
  visibleKey: string;
  visibleDefault: boolean;
  tint: RGB;
  /** 有数据才画卡片；没数据的进「未检测到本地数据」。 */
  active: (ctx: CardContext) => boolean;
  /** compact：只有额度状态、没有 token 用量的小卡，排在前面。 */
  presentation?: (ctx: CardContext) => "standard" | "compact";
  /** 卡头有没有「复制此工具用量图」按钮（Mac 版 cardHead 的 toolID），默认有。 */
  copyable?: (ctx: CardContext) => boolean;
  render: (ctx: CardContext) => ReactNode;
}
