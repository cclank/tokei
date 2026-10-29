import { useState } from "react";
import * as Fmt from "../lib/fmt";
import { doubaoWorkActivityLabel, doubaoWorkHasActivity, doubaoWorkQuota, doubaoWorkQuotaNotice, doubaoWorkQuotaRows, doubaoWorkRange, doubaoWorkSourceCaption } from "../lib/doubaowork";
import { requestDoubaoQuotaConnection } from "../lib/doubaoworkQuotaNative";
import { inTauri } from "../lib/collector";
import { setPref } from "../lib/prefs";
import { L } from "../lib/i18n";
import { CardHead, CostHeadline, HStack, MiniBar, Spacer, ThinDivider, VStack } from "../ui/kit";
import { fs, gradient, T, Theme } from "../ui/theme";
import type { CardContext, CardSpec } from "./spec";

function DoubaoWorkCard({ ctx }: { ctx: CardContext }) {
  const r = doubaoWorkRange(ctx.usage.doubaowork, ctx.range);
  const [current, week] = doubaoWorkQuotaRows(ctx.usage.doubaowork);
  const notice = doubaoWorkQuotaNotice(ctx.usage.doubaowork);
  const quota = doubaoWorkQuota(ctx.usage.doubaowork);
  const hasWindows = (quota?.windows.length ?? 0) > 0;
  const activity = doubaoWorkHasActivity(ctx.usage.doubaowork);
  const [connecting, setConnecting] = useState(false);
  const [connectionError, setConnectionError] = useState(false);
  const connect = async () => {
    if (connecting) return;
    setConnecting(true);
    setConnectionError(false);
    try {
      const next = await requestDoubaoQuotaConnection(ctx.range);
      if (next) setPref("doubaoWorkQuotaEnabled", next.enabled);
    } catch { setConnectionError(true); }
    finally { setConnecting(false); }
  };
  return (
    <VStack gap={11}>
      <CardHead title="Doubao Work" tint={Theme.doubaoWork} />
      {hasWindows ? <>
      <VStack gap={4}>
        <CostHeadline value={current.value} caption={current.caption} />
        {current.detail && <span style={{ fontSize: fs(9), color: T.tertiary }}>{current.detail}</span>}
        {current.remaining != null && <MiniBar value={current.remaining} tint={gradient(Theme.doubaoWork, current.stale ? 0.45 : 1)} />}
      </VStack>
      <VStack gap={4}>
        <HStack gap={5}>
          <span style={{ fontSize: fs(10), color: T.secondary }}>{week.caption}</span>
          <Spacer />
          <span style={{ fontSize: fs(13), fontWeight: 600, fontFamily: "var(--mono)", color: T.primary }}>{week.value}</span>
        </HStack>
        {week.detail && <span style={{ fontSize: fs(9), color: T.tertiary }}>{week.detail}</span>}
        {week.remaining != null && <MiniBar value={week.remaining} tint={gradient(Theme.doubaoWork, week.stale ? 0.45 : 1)} />}
      </VStack>
      {notice && <div style={{ fontSize: fs(9), color: T.tertiary }}>{notice}</div>}
      {activity && <>
        <ThinDivider />
        <div style={{ fontSize: fs(9), color: T.secondary }}>{doubaoWorkActivityLabel(ctx.range)} · {Fmt.human(r.sessions)}</div>
      </>}
      </> : <>
        {activity && <CostHeadline value={Fmt.human(r.sessions)} caption={doubaoWorkActivityLabel(ctx.range)} />}
        <button type="button" className="plain" disabled={connecting} onClick={() => void connect()}
          style={{ textAlign: "left", fontSize: fs(10), color: T.secondary, cursor: connecting ? "wait" : "pointer" }}>
          {L("连接豆包账号查看额度")}
        </button>
        {(!inTauri || connectionError) && <div role="status" style={{ fontSize: fs(9), color: T.tertiary }}>
          {!inTauri ? L("此授权功能仅在 Windows 应用中可用。") : L("尚未读取到额度，请确认登录后点击“读取额度”")}
        </div>}
      </>}
      <div style={{ fontSize: fs(8.5), color: T.tertiary }}>{doubaoWorkSourceCaption(ctx.usage.doubaowork)}</div>
    </VStack>
  );
}

export const doubaoWorkCard: CardSpec = {
  id: "doubaowork",
  name: "Doubao Work",
  visibleKey: "showDoubaoWork",
  visibleDefault: true,
  tint: Theme.doubaoWork,
  active: ({ usage, pref }) => doubaoWorkHasActivity(usage.doubaowork) || doubaoWorkQuota(usage.doubaowork) != null || pref("doubaoWorkQuotaEnabled", false),
  copyable: ({ usage }) => doubaoWorkHasActivity(usage.doubaowork) || (doubaoWorkQuota(usage.doubaowork)?.windows.length ?? 0) > 0,
  render: ctx => <DoubaoWorkCard ctx={ctx} />,
};
