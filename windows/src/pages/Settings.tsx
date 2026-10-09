// 设置页（Mac 版 PanelView.settingsContent）：顶部标题，下面左右两列分块。
// 左列：显示卡片、Provider 额度、诊断、价格表；右列：界面、额度来源（Mac 的「菜单栏」）、隐私与额度、系统。
// Mac 独有、Windows 上还没有实现的块（版本与更新、久坐提醒、多设备同步、远程采集）不显示。
import { useEffect, useState } from "react";
import { CARDS } from "../cards/registry";
import type { CardSpec } from "../cards/spec";
import { inTauri } from "../lib/collector";
import { L, selectedLanguage, setLanguage, type LangSetting } from "../lib/i18n";
import { autostartEnabled, openExternal, setAutostart } from "../lib/native";
import { getPref, setPref, usePrefsVersion } from "../lib/prefs";
import { pushTrayTooltip, useUsageStore } from "../lib/store";
import { Icon } from "../ui/Icon";
import { ThinDivider } from "../ui/kit";
import { FONT_SIZE_KEY, fs, rgba, T, Theme } from "../ui/theme";
import { CARD_CONFIG_KEYS, minimaxKeyStored, PRIVACY_CONFIG_KEYS, writeCollectorFlag } from "./settings/collectorConfig";
import { Note, Segmented, SettingsSection, StackedValue, TintToggleRow, ToggleGrid, ToggleRow } from "./settings/controls";
import { DiagnosticsSection, PricingSection } from "./settings/MaintenanceSections";
import { ProviderQuotaSection } from "./settings/ProviderQuotaSection";
import { TRAY_QUOTA_SOURCES, trayQuotaEnabled } from "../lib/trayQuota";

const GITHUB_URL = "https://github.com/cclank/tokei";

/** AppLanguage.allCases 与各自的选项名：各语言用自己的写法，切到任何语言都认得出来。 */
const LANGUAGE_OPTIONS: { value: LangSetting; label: () => string }[] = [
  { value: "system", label: () => L("跟随系统") },
  { value: "zh", label: () => "中文" }, // l10n-ignore
  { value: "en", label: () => "English" },
  { value: "fr", label: () => "Français" },
  { value: "ja", label: () => "日本語" }, // l10n-ignore
  { value: "ko", label: () => "한국어" },
];

/** 「显示卡片」的顺序照 Mac 版设置页（与首页卡片顺序在末尾几张上不同）。 */
const SETTINGS_CARD_ORDER = [
  "claude", "codex", "gemini", "cursor", "zed", "sub2api", "zai", "grok", "grok-bot",
  "qoder", "qoderwork", "qodercli", "qodercli_cn", "hermes", "zcode", "mimocode", "openclaw",
  "pi", "prime_agent", "workbuddy", "workbuddy-ai", "codebuddy", "deepseek_harness", "opencode",
  "qwencode", "qwenwork", "kimicode", "musecode", "cmdcode", "devin", "minimax",
];

/** 设置页上的名字与卡片「未检测到本地数据」里的名字不同的几张。 */
const CARD_LABELS: Record<string, () => string> = {
  gemini: () => "Gemini / Antigravity",
  qwenwork: () => L("千问办公"),
};

function cardLabel(spec: CardSpec): string {
  const override = CARD_LABELS[spec.id];
  if (override) return override();
  return typeof spec.name === "function" ? spec.name() : spec.name;
}

function settingsCards(): CardSpec[] {
  const rank = (spec: CardSpec) => {
    const index = SETTINGS_CARD_ORDER.indexOf(spec.id);
    return index < 0 ? SETTINGS_CARD_ORDER.length + CARDS.indexOf(spec) : index;
  };
  return [...CARDS].sort((a, b) => rank(a) - rank(b));
}

function GitHubMark({ size }: { size: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 16 16" fill="currentColor" aria-hidden="true">
      <path d="M8 0C3.58 0 0 3.58 0 8c0 3.54 2.29 6.53 5.47 7.59.4.07.55-.17.55-.38 0-.19-.01-.82-.01-1.49-2.01.37-2.53-.49-2.69-.94-.09-.23-.48-.94-.82-1.13-.28-.15-.68-.52-.01-.53.63-.01 1.08.58 1.23.82.72 1.21 1.87.87 2.33.66.07-.52.28-.87.51-1.07-1.78-.2-3.64-.89-3.64-3.95 0-.87.31-1.59.82-2.15-.08-.2-.36-1.02.08-2.12 0 0 .67-.21 2.2.82.64-.18 1.32-.27 2-.27.68 0 1.36.09 2 .27 1.53-1.04 2.2-.82 2.2-.82.44 1.1.16 1.92.08 2.12.51.56.82 1.27.82 2.15 0 3.07-1.87 3.75-3.65 3.95.29.25.54.73.54 1.48 0 1.07-.01 1.93-.01 2.2 0 .21.15.46.55.38A8.013 8.013 0 0016 8c0-4.42-3.58-8-8-8z" />
    </svg>
  );
}

function SettingsHeader({ onClose }: { onClose?: () => void }) {
  const [version, setVersion] = useState<string | null>(null);
  useEffect(() => {
    if (!inTauri) return;
    import("@tauri-apps/api/app")
      .then(({ getVersion }) => getVersion())
      .then(setVersion)
      .catch(() => setVersion(null));
  }, []);
  return (
    <div style={{ display: "flex", alignItems: "center", gap: 10, paddingBottom: 2 }}>
      <span
        style={{
          width: 30,
          height: 30,
          borderRadius: 15,
          flex: "none",
          display: "grid",
          placeItems: "center",
          background: rgba(Theme.claude, 0.16),
          color: rgba(Theme.claude),
        }}
      >
        <Icon name="gearshape.fill" size={fs(13)} strokeWidth={2.4} />
      </span>
      <div style={{ display: "flex", flexDirection: "column", gap: 1, minWidth: 0 }}>
        <div style={{ display: "flex", alignItems: "baseline", gap: 6 }}>
          <span style={{ fontSize: fs(15), fontWeight: 700, color: T.primary }}>{L("设置")}</span>
          {version && <span style={{ fontSize: fs(9), fontFamily: "var(--mono)", color: T.tertiary }}>v{version}</span>}
        </div>
        <span style={{ fontSize: fs(9.5), color: T.tertiary }}>{L("显示、同步和诊断")}</span>
      </div>
      <div style={{ flex: 1 }} />
      <button className="st-circle" title="GitHub" onClick={() => void openExternal(GITHUB_URL)} style={{ width: 24, height: 24 }}>
        <GitHubMark size={13} />
      </button>
      {onClose && (
        <button className="st-circle" title={L("关闭设置")} onClick={onClose} style={{ width: 24, height: 24 }}>
          <Icon name="xmark" size={fs(10)} strokeWidth={3} />
        </button>
      )}
    </div>
  );
}

/** 显示卡片：开关就是首页卡片的显示偏好，几张卡同时决定采集脚本要不要去查它的额度。 */
function AgentsSection() {
  const { refresh } = useUsageStore();
  const toggle = (spec: CardSpec, enabled: boolean) => {
    setPref(spec.visibleKey, enabled);
    const configKey = CARD_CONFIG_KEYS[spec.visibleKey];
    if (!configKey) return;
    if (spec.visibleKey === "showQoderIde") {
      void writeCollectorFlag(configKey, enabled);
    } else if (spec.visibleKey === "showMiniMax") {
      // MiniMax 额度要联网：卡片开着且填过 Key 才查。
      void minimaxKeyStored()
        .then((stored) => writeCollectorFlag(configKey, enabled && stored))
        .then(refresh);
    } else {
      void writeCollectorFlag(configKey, enabled).then(refresh);
    }
  };
  return (
    <SettingsSection icon="square.grid.2x2" title={L("显示卡片")}>
      <ToggleGrid>
        {settingsCards().map((spec) => (
          <TintToggleRow
            key={spec.id}
            name={cardLabel(spec)}
            tint={spec.tint}
            on={getPref(spec.visibleKey, spec.visibleDefault)}
            onChange={(enabled) => toggle(spec, enabled)}
          />
        ))}
      </ToggleGrid>
    </SettingsSection>
  );
}

function AppearanceSection() {
  const fontSize = getPref<string>(FONT_SIZE_KEY, "small") === "large" ? "large" : "small";
  return (
    <SettingsSection icon="textformat.size" title={L("界面")}>
      <StackedValue title={L("语言")}>
        <select
          className="st-select"
          aria-label={L("语言")}
          value={selectedLanguage()}
          onChange={(event) => setLanguage(event.target.value as LangSetting)}
          style={{ fontSize: fs(10) }}
        >
          {LANGUAGE_OPTIONS.map((option) => (
            <option key={option.value} value={option.value}>
              {option.label()}
            </option>
          ))}
        </select>
      </StackedValue>
      <StackedValue title={L("字体大小")}>
        <Segmented
          label={L("字体大小")}
          value={fontSize}
          onChange={(value) => setPref(FONT_SIZE_KEY, value)}
          options={[
            { value: "small", label: L("小") },
            { value: "large", label: L("大") },
          ]}
        />
      </StackedValue>
    </SettingsSection>
  );
}

/**
 * Mac 的「菜单栏」块。Windows 托盘图标画不了文字，样式、信息量、预览都没有意义，
 * 只保留额度来源开关：它们决定托盘悬停提示里列哪些窗口。
 */
function TrayQuotaSection() {
  const { usage } = useUsageStore();
  return (
    <SettingsSection icon="menubar.rectangle" title={L("额度来源")}>
      <ToggleGrid>
        {TRAY_QUOTA_SOURCES.map((source) => (
          <TintToggleRow
            key={source.id}
            name={source.label()}
            tint={source.tint}
            on={trayQuotaEnabled(source)}
            onChange={(enabled) => {
              setPref(source.key, enabled);
              if (usage) pushTrayTooltip(usage);
            }}
          />
        ))}
      </ToggleGrid>
    </SettingsSection>
  );
}

function PrivacySection() {
  const { refresh } = useUsageStore();
  const row = (title: string, prefKey: string) => (
    <ToggleRow
      title={title}
      on={getPref(prefKey, false)}
      onChange={(enabled) => {
        setPref(prefKey, enabled);
        void writeCollectorFlag(PRIVACY_CONFIG_KEYS[prefKey], enabled).then(refresh);
      }}
    />
  );
  return (
    <SettingsSection icon="lock.shield" title={L("隐私与额度")}>
      {row(L("Grok 实时额度查询"), "grokLiveQuotaEnabled")}
      <Note>{L("默认只读本机 Grok 日志中的额度快照，不访问网络。开启后才会用本地登录凭据请求 Grok 账单接口，以便拿到最新剩余额度。")}</Note>
      <ThinDivider />
      {row(L("Grok Bot 额度查询"), "grokBotQuotaEnabled")}
      <ThinDivider />
      {row(L("千问办公额度查询"), "qwenWorkQuotaEnabled")}
      <Note>
        {L(
          "默认关闭。开启后，Tokei 仅连接千问办公桌面端在本机 127.0.0.1 提供的受保护接口；千问办公可能随之向官方服务刷新额度。Tokei 不读取或保存登录凭据，需保持千问办公已登录并运行。",
        )}
      </Note>
    </SettingsSection>
  );
}

/** 「登录时启动」= Windows 的开机自启（tauri-plugin-autostart）。 */
function SystemSection() {
  const [enabled, setEnabled] = useState<boolean | null>(null);
  const [error, setError] = useState("");
  useEffect(() => {
    const load = () =>
      autostartEnabled()
        .then(setEnabled)
        .catch((err) => {
          setEnabled(false);
          setError(String(err));
        });
    void load();
    // 托盘右键菜单里也能勾「登录时启动」，面板再次弹出时按实际状态刷新。
    window.addEventListener("focus", load);
    return () => window.removeEventListener("focus", load);
  }, []);
  const toggle = async (next: boolean) => {
    setError("");
    try {
      await setAutostart(next);
      setEnabled(await autostartEnabled());
    } catch (err) {
      setError(String(err));
      setEnabled(await autostartEnabled().catch(() => !next));
    }
  };
  return (
    <SettingsSection icon="gearshape.2" title={L("系统")}>
      <ToggleRow title={L("登录时启动")} on={enabled === true} disabled={enabled === null} onChange={(next) => void toggle(next)} />
      {error && <Note color={rgba(Theme.red, 0.85)}>{error}</Note>}
    </SettingsSection>
  );
}

const column = { display: "flex", flexDirection: "column", gap: 11, minWidth: 0 } as const;

export default function SettingsPage({ onClose }: { onClose?: () => void } = {}) {
  // 换语言、字号时整页重算（App 里把这一页缓存成同一个元素，不会顺带重渲染）。
  usePrefsVersion();
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
      <SettingsHeader onClose={onClose} />
      <div style={{ display: "grid", gridTemplateColumns: "minmax(0, 1fr) minmax(0, 1fr)", gap: 11, alignItems: "start" }}>
        <div style={column}>
          <AgentsSection />
          <ProviderQuotaSection />
          <DiagnosticsSection />
          <PricingSection />
        </div>
        <div style={column}>
          <AppearanceSection />
          <TrayQuotaSection />
          <PrivacySection />
          <SystemSection />
        </div>
      </div>
    </div>
  );
}
