// 「Provider 额度」：Sub2API 地址与 Key、z.ai 区域与 Key、MiniMax Token Plan Key
// （Mac 版 settingsProviderQuotaSection / loadProviderSettings / saveProviderSettings / clearProviderToken）。
// Key 存 Windows 凭据管理器，前端只知道「存没存」，从不读回、也不显示。
import { useCallback, useEffect, useState } from "react";
import { L } from "../../lib/i18n";
import { deleteSecret, hasSecret, readTokeiConfig, setSecret, updateTokeiConfig, type SecretProvider } from "../../lib/native";
import { getPref } from "../../lib/prefs";
import { useUsageStore } from "../../lib/store";
import { ThinDivider } from "../../ui/kit";
import { fs, rgba, T, Theme, type RGB } from "../../ui/theme";
import { CARDS } from "../../cards/registry";
import { ActionButton, Note, ProviderField, Segmented, SettingsSection } from "./controls";

type ZaiRegion = "global" | "bigmodel-cn";

function configString(config: Record<string, unknown>, key: string): string | null {
  const value = config[key];
  if (typeof value !== "string") return null;
  const cleaned = value.trim();
  return cleaned ? cleaned : null;
}

/** HTTPS，或只连本机的 HTTP；不许带账号密码、查询串和锚点（validSub2APIBaseURL）。 */
function validSub2APIBaseURL(value: string): boolean {
  if (value.includes("?") || value.includes("#")) return false;
  let url: URL;
  try {
    url = new URL(value);
  } catch {
    return false;
  }
  if (!url.hostname || url.username || url.password) return false;
  const scheme = url.protocol.toLowerCase();
  if (scheme === "https:") return true;
  if (scheme !== "http:") return false;
  const host = url.hostname.toLowerCase().replace(/^\[|\]$/g, "");
  return host === "localhost" || host === "127.0.0.1" || host === "::1";
}

async function stored(provider: SecretProvider): Promise<boolean> {
  try {
    return await hasSecret(provider);
  } catch {
    return false;
  }
}

function miniMaxCardShown(): boolean {
  const spec = CARDS.find((card) => card.visibleKey === "showMiniMax");
  return getPref("showMiniMax", spec?.visibleDefault ?? true);
}

function ProviderTitle({ name, tint }: { name: string; tint: RGB }) {
  return <span style={{ fontSize: fs(10), fontWeight: 600, color: rgba(tint) }}>{name}</span>;
}

function ClearButton({ title, onClick }: { title: string; onClick: () => void }) {
  return (
    <div style={{ display: "flex", justifyContent: "flex-end" }}>
      <ActionButton icon="trash" title={title} onClick={onClick} />
    </div>
  );
}

export function ProviderQuotaSection() {
  const { refresh } = useUsageStore();
  const [sub2APIBaseURL, setSub2APIBaseURL] = useState("");
  const [sub2APIKey, setSub2APIKey] = useState("");
  const [sub2APIKeyStored, setSub2APIKeyStored] = useState(false);
  const [zaiRegion, setZaiRegion] = useState<ZaiRegion>("global");
  const [zaiKey, setZaiKey] = useState("");
  const [zaiKeyStored, setZaiKeyStored] = useState(false);
  const [miniMaxKey, setMiniMaxKey] = useState("");
  const [miniMaxKeyStored, setMiniMaxKeyStored] = useState(false);
  const [result, setResult] = useState("");
  const [busy, setBusy] = useState(false);

  /** 重新读一遍存储状态；返回 MiniMax 有没有 Key，保存后要据此开关联网查询。 */
  const load = useCallback(async (): Promise<boolean> => {
    const [config, sub2api, zai, minimax] = await Promise.all([
      readTokeiConfig().catch(() => ({}) as Record<string, unknown>),
      stored("sub2api"),
      stored("zai"),
      stored("minimax"),
    ]);
    setSub2APIBaseURL(configString(config, "sub2api_base_url") ?? "");
    setZaiRegion(configString(config, "zai_region") === "bigmodel-cn" ? "bigmodel-cn" : "global");
    setSub2APIKeyStored(sub2api);
    setZaiKeyStored(zai);
    setMiniMaxKeyStored(minimax);
    return minimax;
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const save = async () => {
    const baseURL = sub2APIBaseURL.trim();
    if (baseURL && !validSub2APIBaseURL(baseURL)) {
      setResult(L("Sub2API URL 仅支持 HTTPS 或本机 HTTP"));
      return;
    }
    setBusy(true);
    try {
      await updateTokeiConfig({ sub2api_base_url: baseURL || null, zai_region: zaiRegion });
      const keys: [SecretProvider, string][] = [
        ["sub2api", sub2APIKey],
        ["zai", zaiKey],
        ["minimax", miniMaxKey],
      ];
      for (const [provider, value] of keys) {
        if (value.trim()) await setSecret(provider, value.trim());
      }
      setSub2APIKey("");
      setZaiKey("");
      setMiniMaxKey("");
      const minimax = await load();
      await updateTokeiConfig({ minimax_quota_enabled: miniMaxCardShown() && minimax });
      setResult(L("已保存"));
      refresh();
    } catch (err) {
      console.error(err);
      setResult(L("保存失败"));
    } finally {
      setBusy(false);
    }
  };

  const clear = async (provider: SecretProvider) => {
    setBusy(true);
    try {
      await deleteSecret(provider);
      await load();
      if (provider === "minimax") await updateTokeiConfig({ minimax_quota_enabled: false });
      setResult(L("已清除"));
      refresh();
    } catch (err) {
      console.error(err);
      setResult(L("清除失败"));
    } finally {
      setBusy(false);
    }
  };

  const keptPlaceholder = L("已保存，留空不修改");

  return (
    <SettingsSection icon="key.horizontal.fill" title={L("Provider 额度")}>
      <ProviderTitle name="Sub2API" tint={Theme.sub2api} />
      <ProviderField label="Base URL" placeholder="https://api.example.com" value={sub2APIBaseURL} onChange={setSub2APIBaseURL} />
      <ProviderField
        label="API Key"
        placeholder={sub2APIKeyStored ? keptPlaceholder : "Group API Key"}
        value={sub2APIKey}
        onChange={setSub2APIKey}
        secure
      />
      {sub2APIKeyStored && <ClearButton title={L("清除 Sub2API 密钥")} onClick={() => void clear("sub2api")} />}

      <ThinDivider />

      <ProviderTitle name="z.ai / GLM" tint={Theme.zai} />
      <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
        <span style={{ width: 52, flex: "none", fontSize: fs(9.5), color: T.tertiary }}>{L("区域")}</span>
        <Segmented
          label={L("z.ai 区域")}
          value={zaiRegion}
          onChange={setZaiRegion}
          options={[
            { value: "global", label: "Global" },
            { value: "bigmodel-cn", label: "BigModel CN" },
          ]}
          style={{ flex: 1, minWidth: 0 }}
        />
      </div>
      <ProviderField
        label="API Key"
        placeholder={zaiKeyStored ? keptPlaceholder : "Z_AI_API_KEY"}
        value={zaiKey}
        onChange={setZaiKey}
        secure
      />
      {zaiKeyStored && <ClearButton title={L("清除 z.ai 密钥")} onClick={() => void clear("zai")} />}

      <ThinDivider />

      <ProviderTitle name="MiniMax Code" tint={Theme.minimax} />
      <Note>
        {L("Token 统计读本机数据，无需配置。填入 Token Plan 的 Key（sk-cp-…）后才会联网查询 5 小时与周额度；中国区与国际区自动识别。")}
      </Note>
      <ProviderField
        label="API Key"
        placeholder={miniMaxKeyStored ? keptPlaceholder : "Token Plan Key"}
        value={miniMaxKey}
        onChange={setMiniMaxKey}
        secure
      />
      {miniMaxKeyStored && <ClearButton title={L("清除 MiniMax 密钥")} onClick={() => void clear("minimax")} />}

      <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
        <ActionButton icon="checkmark.circle" title={L("保存 Provider 设置")} onClick={() => void save()} disabled={busy} />
        <div style={{ flex: 1 }} />
        {result && (
          <span style={{ fontSize: fs(8.5), color: rgba(result === L("已保存") ? Theme.green : Theme.orange) }}>{result}</span>
        )}
      </div>
    </SettingsSection>
  );
}
