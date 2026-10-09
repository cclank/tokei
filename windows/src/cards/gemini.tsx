// 待移植：占位卡片，先不显示（active 恒为 false）。
import { Theme } from "../ui/theme";
import type { CardSpec } from "./spec";

export const geminiCard: CardSpec = {
  id: "gemini",
  name: "Gemini",
  visibleKey: "showGemini",
  visibleDefault: true,
  tint: Theme.gemini,
  active: () => false,
  render: () => null,
};
