// 设置开关与采集脚本 `~/.tokei/config.json` 的对应关系（Mac 版 SyncManager.setQoderIdeEnabled /
// setGrokLiveQuotaEnabled / setQwenWorkQuotaEnabled / setProviderQuotaEnabled）。
// 只按键合并写入（updateTokeiConfig），不整份覆盖，同步等其他字段原样保留。
import { CARDS } from "../../cards/registry";
import { hasSecret, updateTokeiConfig } from "../../lib/native";
import { getPref } from "../../lib/prefs";

/** 「显示卡片」里会顺带开关采集的几张卡：偏好键 → config.json 的键。 */
export const CARD_CONFIG_KEYS: Record<string, string> = {
  showQoderIde: "qoder_ide_enabled",
  showGemini: "antigravity_quota_enabled",
  showDevin: "devin_quota_enabled",
  showMiniMax: "minimax_quota_enabled",
  showCursor: "cursor_quota_enabled",
  showZed: "zed_quota_enabled",
  showSub2API: "sub2api_quota_enabled",
  showZai: "zai_quota_enabled",
};

/** 「隐私与额度」里的开关：偏好键 → config.json 的键（都默认关）。 */
export const PRIVACY_CONFIG_KEYS: Record<string, string> = {
  grokLiveQuotaEnabled: "grok_live_quota_enabled",
  grokBotQuotaEnabled: "grok_bot_quota_enabled",
  qwenWorkQuotaEnabled: "qwenwork_quota_enabled",
};

export async function writeCollectorFlag(configKey: string, enabled: boolean): Promise<void> {
  try {
    await updateTokeiConfig({ [configKey]: enabled });
  } catch (err) {
    console.error(err);
  }
}

export async function minimaxKeyStored(): Promise<boolean> {
  try {
    return await hasSecret("minimax");
  } catch {
    return false;
  }
}

function cardShown(visibleKey: string): boolean {
  const spec = CARDS.find((card) => card.visibleKey === visibleKey);
  return getPref(visibleKey, spec?.visibleDefault ?? false);
}

/**
 * 启动时把开关的当前值落盘（Mac 版 syncQoderIdeConfigOnLaunch / syncGrokLiveQuotaConfigOnLaunch /
 * syncQwenWorkQuotaConfigOnLaunch / syncProviderQuotaConfigOnLaunch）：Qoder Desktop 卡片默认开，
 * 但采集脚本默认不采，开关从没动过就永远不会写进 config.json。MiniMax 要卡片开着且填过 Key 才联网查。
 */
export async function syncCollectorConfigOnLaunch(): Promise<void> {
  const patch: Record<string, boolean> = {};
  for (const [visibleKey, configKey] of Object.entries(CARD_CONFIG_KEYS)) {
    if (visibleKey === "showMiniMax") continue;
    patch[configKey] = cardShown(visibleKey);
  }
  for (const [prefKey, configKey] of Object.entries(PRIVACY_CONFIG_KEYS)) {
    patch[configKey] = getPref(prefKey, false);
  }
  patch.minimax_quota_enabled = cardShown("showMiniMax") && (await minimaxKeyStored());
  try {
    await updateTokeiConfig(patch);
  } catch (err) {
    console.error(err);
  }
}
