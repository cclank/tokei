import { useEffect, useRef, useState } from "react";
import { call, inTauri } from "../../lib/collector";
import { L } from "../../lib/i18n";
import { updateTokeiConfig } from "../../lib/native";
import { getPref, setPref, usePrefsVersion } from "../../lib/prefs";
import { useUsageStore } from "../../lib/store";
import { ThinDivider } from "../../ui/kit";
import { PRIVACY_CONFIG_KEYS } from "./collectorConfig";
import { ActionButton, Note, SettingsSection, ToggleRow } from "./controls";

type Authorization = { status: string };

function authorizationText(status: string): string {
  if (status === "authorized") return L("授权成功，可在 Grok Bot 卡片查看");
  if (status === "unsupported_platform") return L("此授权功能仅在 Windows 应用中可用。");
  if (status === "unsupported_format") return L("Grok Bot 的登录凭据格式暂不支持，请更新 Tokei。");
  return L("未授权，或 Grok Bot 尚未登录");
}

export function PrivacySection() {
  const { refresh } = useUsageStore();
  usePrefsVersion();
  const enabled = getPref("grokBotQuotaEnabled", false);
  const [saving, setSaving] = useState<string | null>(null);
  const [error, setError] = useState("");
  const [authorizing, setAuthorizing] = useState(false);
  const [authorization, setAuthorization] = useState<Authorization | null>(null);
  const generation = useRef(0);
  const alive = useRef(true);
  const authorizationRunning = useRef(false);
  useEffect(() => {
    alive.current = true;
    const load = () => {
      if (!inTauri || authorizationRunning.current) return;
      const current = ++generation.current;
      void call<Authorization>("grok_bot_authorization_status").then((value) => {
        if (alive.current && generation.current === current) setAuthorization(value ?? { status: "unsupported_platform" });
      }).catch(() => {
        if (alive.current && generation.current === current) setAuthorization({ status: "unavailable" });
      });
    };
    if (enabled) load();
    window.addEventListener("focus", load);
    return () => { alive.current = false; generation.current++; window.removeEventListener("focus", load); };
  }, [enabled]);

  const change = async (key: string, next: boolean) => {
    if (saving) return;
    setSaving(key);
    setError("");
    try {
      if (key === "shareBasicActivity") await call("set_activity_statistics", { enabled: next });
      else await updateTokeiConfig({ [PRIVACY_CONFIG_KEYS[key]]: next });
      setPref(key, next);
      if (key !== "shareBasicActivity") refresh();
    } catch (err) {
      if (alive.current) setError(String(err));
    } finally {
      if (alive.current) setSaving(null);
    }
  };

  const authorize = async () => {
    if (authorizationRunning.current || !enabled) return;
    authorizationRunning.current = true;
    const current = ++generation.current;
    setAuthorizing(true);
    setError("");
    try {
      const value = await call<Authorization>("authorize_grok_bot");
      if (alive.current && current === generation.current) {
        setAuthorization(value ?? { status: "unsupported_platform" });
        if (value?.status === "authorized") refresh();
      }
    } catch {
      if (alive.current && current === generation.current) setAuthorization({ status: "unavailable" });
    } finally {
      authorizationRunning.current = false;
      if (alive.current) setAuthorizing(false);
    }
  };

  const row = (title: string, key: string) => <ToggleRow title={title} on={getPref(key, key === "shareBasicActivity")}
    disabled={saving !== null || key === "grokBotQuotaEnabled" && authorizing} onChange={(next) => void change(key, next)} />;
  return (
    <SettingsSection icon="lock.shield" title={L("隐私与额度")}>
      {row(L("应用活跃统计"), "shareBasicActivity")}
      <Note>{L("用于了解应用的活跃安装数量，默认开启，可随时关闭。每次启动仅尝试上报一次随机安装 ID、Tokei 版本及系统名称和主次版本。服务端记录首次和最近活跃时间，并保存最近一次来源 IP。不会上传账号、项目、对话、Token、费用或额度。关闭后停止发送，重新开启于下次启动生效；安装 ID 不参与多设备同步。")}</Note>
      <ThinDivider />
      {row(L("Claude Code CLI 额度查询"), "claudeCLIQuotaEnabled")}
      <Note>{L("默认关闭。开启后仅在 Claude Desktop 缓存不可用时，使用 Claude Code CLI 已有登录态向 Anthropic 查询 5h、周及模型额度，并缓存 5 分钟。登录 Token 只在内存中使用，不写入 Tokei 文件。")}</Note>
      <ThinDivider />
      {row(L("Grok 实时额度查询"), "grokLiveQuotaEnabled")}
      <Note>{L("默认只读本机 Grok 日志中的额度快照，不访问网络。开启后才会用本地登录凭据请求 Grok 账单接口，以便拿到最新剩余额度。")}</Note>
      <ThinDivider />
      {row(L("Grok Bot 额度查询"), "grokBotQuotaEnabled")}
      <Note>{L("开启后使用 Grok Bot 自身登录态查询官方额度和 Token，并按 5 分钟缓存。首次使用请点击“授权 Grok Bot”；授权在重启和升级后保留。登录 Token 仅在辅助进程内存中使用。")}</Note>
      {enabled && <>
        <ActionButton icon="key.horizontal.fill" title={authorizing ? L("等待授权…") : authorization?.status === "authorized" ? L("重新授权 Grok Bot") : L("授权 Grok Bot")}
          disabled={authorizing || saving !== null} onClick={() => void authorize()} />
        {authorization && !authorizing && <Note>{authorizationText(authorization.status)}</Note>}
      </>}
      <ThinDivider />
      {row(L("千问办公额度查询"), "qwenWorkQuotaEnabled")}
      <Note>{L("默认关闭。开启后，Tokei 仅连接千问办公桌面端在本机 127.0.0.1 提供的受保护接口；千问办公可能随之向官方服务刷新额度。Tokei 不读取或保存登录凭据，需保持千问办公已登录并运行。")}</Note>
      {error && <Note>{error}</Note>}
    </SettingsSection>
  );
}
