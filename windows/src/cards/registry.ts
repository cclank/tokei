// 卡片顺序与 Mac 版 PanelView.toolCards(for:) 一致。
import { claudeCard } from "./claude";
import { codexCard } from "./codex";
import { geminiCard } from "./gemini";
import { grokBotCard, grokCard } from "./grok";
import { hermesCard } from "./hermes";
import { openclawCard } from "./openclaw";
import { cursorCard, devinCard, minimaxCard, sub2apiCard, zaiCard, zedCard } from "./providerQuota";
import { qodercliCard, qodercliCNCard, qoderIdeCard, qoderworkCard } from "./qoder";
import { qwenworkCard } from "./qwenwork";
import type { CardSpec } from "./spec";
import {
  cmdcodeCard,
  codebuddyCard,
  deepseekHarnessCard,
  kimicodeCard,
  mimocodeCard,
  musecodeCard,
  opencodeCard,
  piCard,
  primeAgentCard,
  qwencodeCard,
  workbuddyAICard,
  workbuddyCard,
  zcodeCard,
} from "./tokenUsage";

export const CARDS: CardSpec[] = [
  claudeCard,
  codexCard,
  geminiCard,
  cursorCard,
  zedCard,
  sub2apiCard,
  zaiCard,
  grokCard,
  grokBotCard,
  qoderIdeCard,
  qoderworkCard,
  qodercliCard,
  qodercliCNCard,
  hermesCard,
  zcodeCard,
  mimocodeCard,
  openclawCard,
  piCard,
  primeAgentCard,
  workbuddyCard,
  workbuddyAICard,
  codebuddyCard,
  deepseekHarnessCard,
  opencodeCard,
  qwencodeCard,
  qwenworkCard,
  devinCard,
  minimaxCard,
  kimicodeCard,
  musecodeCard,
  cmdcodeCard,
];
