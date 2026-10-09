// 待移植：占位卡片，先不显示（active 恒为 false）。
import { Theme } from "../ui/theme";
import type { CardSpec } from "./spec";

export const grokCard: CardSpec = {
  id: "grok",
  name: "Grok",
  visibleKey: "showGrok",
  visibleDefault: true,
  tint: Theme.grok,
  active: () => false,
  render: () => null,
};

export const grokBotCard: CardSpec = {
  id: "grok-bot",
  name: "Grok Bot",
  visibleKey: "showGrokBot",
  visibleDefault: true,
  tint: Theme.grokBot,
  active: () => false,
  render: () => null,
};
