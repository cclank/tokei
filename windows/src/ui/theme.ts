// 设计系统：颜色与 Mac 版 Design.swift 的 Theme 一一对应。
// 颜色存成 0–1 的 RGB，按需要的透明度生成 CSS 颜色（Swift 的 tint.opacity(x)）。
import { getPref } from "../lib/prefs";

export type RGB = readonly [number, number, number];

export const Theme = {
  claude: [0.92, 0.52, 0.4],
  codex: [0.42, 0.68, 0.98],
  gemini: [0.62, 0.52, 0.92],
  cursor: [0.72, 0.77, 0.9],
  zed: [0.93, 0.38, 0.3],
  sub2api: [0.18, 0.78, 0.85],
  zai: [0.38, 0.67, 0.98],
  grok: [0.65, 0.68, 0.75],
  grokBot: [0.95, 0.4, 0.64],
  qoder: [0.9, 0.75, 0.35],
  qoderwork: [0.75, 0.65, 0.3],
  qodercli: [0.96, 0.84, 0.45],
  qodercliCN: [0.98, 0.62, 0.35],
  hermes: [0.4, 0.82, 0.6],
  zcode: [0.52, 0.8, 0.34],
  mimocode: [0.95, 0.5, 0.26],
  openclaw: [0.85, 0.45, 0.68],
  pi: [0.74, 0.58, 0.95],
  primeAgent: [0.96, 0.58, 0.28],
  workbuddy: [0.25, 0.78, 0.72],
  workbuddyAI: [0.36, 0.66, 0.94],
  codebuddy: [0.46, 0.58, 0.96],
  deepseekHarness: [0.18, 0.58, 0.94],
  opencode: [0.55, 0.75, 0.9],
  qwencode: [0.48, 0.55, 0.95],
  qwenwork: [0.24, 0.72, 0.68],
  kimicode: [0.2, 0.78, 0.66],
  musecode: [0.1, 0.42, 0.92],
  cmdcode: [0.22, 0.68, 0.32],
  devin: [0.42, 0.47, 0.98],
  minimax: [0.91, 0.25, 0.4],
  orange: [1.0, 0.62, 0.04],
  red: [1.0, 0.27, 0.23],
  green: [0.2, 0.78, 0.35],
  cyan: [0.35, 0.78, 0.98],
} as const satisfies Record<string, RGB>;

export type ThemeColor = keyof typeof Theme;

export function rgba(color: RGB, alpha = 1): string {
  const [r, g, b] = color.map((v) => Math.round(v * 255));
  return `rgba(${r}, ${g}, ${b}, ${alpha})`;
}

/** Swift 的 tint.gradient：同色从上到下略微变暗。 */
export function gradient(color: RGB, alpha = 1): string {
  const darker: RGB = [color[0] * 0.85, color[1] * 0.85, color[2] * 0.85];
  return `linear-gradient(180deg, ${rgba(color, alpha)}, ${rgba(darker, alpha)})`;
}

export const T = {
  primary: "rgba(255, 255, 255, 0.97)",
  secondary: "rgba(255, 255, 255, 0.82)",
  tertiary: "rgba(255, 255, 255, 0.58)",
};

/** 「primary.opacity(x)」：深色界面里 primary 就是白色。 */
export const fill = (alpha: number) => `rgba(255, 255, 255, ${alpha})`;

export const FONT_SIZE_KEY = "panelFontSize";

/** 字号设置（小 / 大），对应 Theme.fontSize(points)。 */
export function fs(points: number): number {
  return getPref<string>(FONT_SIZE_KEY, "small") === "large" ? points * 1.12 : points;
}

export const CARD_RADIUS = 16;
export const OUTER_PAD = 15;
