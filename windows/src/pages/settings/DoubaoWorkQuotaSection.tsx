import { useEffect, useState } from "react";
import { inTauri } from "../../lib/collector";
import { connectDoubaoQuota, DOUBAO_QUOTA_PREF, doubaoQuotaConnection, refreshDoubaoQuota, setDoubaoQuotaEnabled, type DoubaoQuotaConnection } from "../../lib/doubaoworkQuotaNative";
import { L } from "../../lib/i18n";
import { getPref, setPref, usePrefsVersion } from "../../lib/prefs";
import { useUsageStore } from "../../lib/store";
import { ActionButton, Note, SettingsSection, ToggleRow } from "./controls";

export function DoubaoWorkQuotaSection() {
  usePrefsVersion();
  const { refresh } = useUsageStore();
  const enabled = getPref(DOUBAO_QUOTA_PREF, false);
  const [connection, setConnection] = useState<DoubaoQuotaConnection | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(false);
  useEffect(() => {
    let disposed = false;
    let off: (() => void) | undefined;
    const load = () => {
      if (!inTauri) return;
      void doubaoQuotaConnection().then(value => {
        if (disposed) return;
        setConnection(value);
        setPref(DOUBAO_QUOTA_PREF, value.enabled);
      }).catch(() => { if (!disposed) setError(true); });
    };
    load();
    window.addEventListener("focus", load);
    if (inTauri) void import("@tauri-apps/api/event").then(async ({ listen }) => {
      const unlisten = await listen("tokei://doubaowork-quota", load);
      if (disposed) unlisten(); else off = unlisten;
    }).catch(() => { if (!disposed) setError(true); });
    return () => { disposed = true; off?.(); window.removeEventListener("focus", load); };
  }, []);

  const run = async (operation: () => Promise<DoubaoQuotaConnection>) => {
    if (busy) return;
    setBusy(true);
    setError(false);
    try {
      const next = await operation();
      setConnection(next);
      setPref(DOUBAO_QUOTA_PREF, next.enabled);
      refresh();
    } catch {
      setError(true);
      // The backend config remains authoritative even if creating a window failed.
      if (inTauri) void doubaoQuotaConnection().then(value => {
        setConnection(value); setPref(DOUBAO_QUOTA_PREF, value.enabled);
      }).catch(() => {});
    } finally { setBusy(false); }
  };

  const status = connection?.status;
  return (
    <SettingsSection icon="lock.shield" title={L("豆包工作额度查询")}>
      <Note>{L("额度连接为试验功能，登录兼容性仍在验证。")}</Note>
      <ToggleRow title={L("豆包工作额度查询")} on={enabled} disabled={busy || !inTauri}
        onChange={next => void run(() => setDoubaoQuotaEnabled(next))} />
      <Note>{L("首次连接时登录豆包官网，登录状态在 Tokei 中保留。之后每 5 分钟静默刷新额度；登录失效时不会自动弹窗。关闭后停止查询，保留登录状态。")}</Note>
      <ActionButton icon="key.horizontal.fill" title={L("连接豆包工作额度")} disabled={busy || !inTauri}
        onClick={() => void run(connectDoubaoQuota)} />
      {enabled && <ActionButton icon="arrow.clockwise" title={L("读取额度")} disabled={busy || !inTauri}
        onClick={() => void run(refreshDoubaoQuota)} />}
      {!inTauri ? <Note>{L("此授权功能仅在 Windows 应用中可用。")}</Note>
        : error ? <Note>{L("保存失败")}</Note>
        : enabled && status === "connected" ? <Note>{L("已连接，后续每 5 分钟静默刷新")}</Note>
        : enabled && status === "refreshing" ? <Note>{L("正在读取官方额度…")}</Note>
        : enabled && status === "login_required" ? <Note>{L("请在豆包官网完成登录。登录状态在 Tokei 中保留，后续静默刷新；不会读取其他应用的登录凭据。")}</Note>
        : enabled ? <Note>{L("尚未读取到额度，请确认登录后点击“读取额度”")}</Note> : null}
    </SettingsSection>
  );
}
