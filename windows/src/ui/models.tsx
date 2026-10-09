// 「按模型」展开列表与每个模型的明细标签行（PanelView 的 modelDisclosure /
// tokenModelDisclosure / modelDetailRow）。
import { useState, type ReactNode } from "react";
import * as Fmt from "../lib/fmt";
import { data, L } from "../lib/i18n";
import { modelPerf, type PerfModelStat, type PerfStat, type TokenModelStat } from "../lib/types";
import { Icon } from "./Icon";
import { Disclosure, HStack, Spacer } from "./kit";
import { fill, fs, rgba, T, type RGB } from "./theme";

const MONO = "var(--mono)";

export interface ModelRow {
  id: string;
  name: string;
  pin: number;
  pout: number;
  pcr: number;
  cost: number;
  costCny?: number | null;
  credits?: number;
  total: number;
  hit: number;
  tokIn: number;
  tokOut: number;
  tokCR: number;
  tokCW: number;
  tokReason?: number;
  /** 输入 / 输出已含缓存、推理（DeepSeek Harness 那种口径）。 */
  componentsAreSubtotals?: boolean;
  priceRef?: string | null;
  perf?: PerfModelStat;
  hasBreakdown: boolean;
}

function DetailTag({ value, label, tint }: { value: string; label: string; tint: RGB }) {
  return (
    <span className="tag" style={{ background: rgba(tint, 0.08), boxShadow: `inset 0 0 0 0.5px ${rgba(tint, 0.18)}` }}>
      <span style={{ fontSize: fs(9.5), color: T.secondary }}>{label}</span>
      <span style={{ fontSize: fs(10), fontWeight: 600, fontFamily: MONO, color: T.primary }}>{value}</span>
    </span>
  );
}

function TintTag({ tint, children, title, strong = false }: { tint: RGB; children: ReactNode; title?: string; strong?: boolean }) {
  return (
    <span
      className="tag"
      title={title}
      style={{
        background: rgba(tint, strong ? 0.12 : 0.08),
        boxShadow: `inset 0 0 0 0.5px ${rgba(tint, strong ? 0.25 : 0.18)}`,
      }}
    >
      {children}
    </span>
  );
}

export function ModelDetailRow({ row, tint }: { row: ModelRow; tint: RGB }) {
  const tagValue = { fontSize: fs(10), fontWeight: 600, fontFamily: MONO, color: rgba(tint) } as const;
  const tagLabel = { fontSize: fs(9.5), color: T.secondary } as const;
  const sub = row.componentsAreSubtotals;
  const perf = row.perf;
  return (
    <div style={{ display: "flex", paddingTop: 5, paddingBottom: 2 }}>
      <div style={{ width: 20, flex: "none" }} />
      <div style={{ display: "flex", flexWrap: "wrap", gap: 4, minWidth: 0 }}>
        <DetailTag value={`↓ ${Fmt.human(row.tokIn)}`} label={L("输入")} tint={tint} />
        <DetailTag value={`↑ ${Fmt.human(row.tokOut)}`} label={L("输出")} tint={tint} />
        {row.tokCR > 0 && <DetailTag value={`⚡ ${Fmt.human(row.tokCR)}`} label={sub ? L("其中缓存读") : L("缓存读")} tint={tint} />}
        {row.tokCW > 0 && <DetailTag value={`✎ ${Fmt.human(row.tokCW)}`} label={sub ? L("其中缓存写") : L("缓存写")} tint={tint} />}
        {(row.tokReason ?? 0) > 0 && (
          <DetailTag value={`◉ ${Fmt.human(row.tokReason ?? 0)}`} label={sub ? L("其中推理") : L("推理")} tint={tint} />
        )}
        {perf && (
          <TintTag
            tint={tint}
            title={
              perf.ttft == null
                ? L("平均输出速度来自 %@ 个请求", perf.n)
                : L("平均输出速度来自 %@ 个请求，TTFT 中位数来自其中 %@ 个", perf.n, perf.tn ?? perf.n)
            }
          >
            <span style={tagLabel}>{L("平均速度")}</span>
            <span style={tagValue}>{Fmt.tps(perf.tps)}</span>
            {perf.ttft != null && (
              <>
                <span style={{ ...tagValue, opacity: 0.6 }}>·</span>
                <span style={tagLabel}>{L("TTFT 中位数")}</span>
                <span style={tagValue}>{Fmt.seconds(perf.ttft)}</span>
              </>
            )}
          </TintTag>
        )}
        {row.hit > 0 && (
          <TintTag tint={tint}>
            <span style={tagLabel}>{L("命中")}</span>
            <span style={tagValue}>{row.hit.toFixed(0)}%</span>
          </TintTag>
        )}
        {(row.pin > 0 || row.pout > 0) && (
          <TintTag
            tint={tint}
            strong
            title={
              row.priceRef ? L("没有公开价格，按 %@ 的单价估算", data(row.priceRef)) : L("每百万 token 的输入 / 输出单价，读 = 缓存读")
            }
          >
            <span style={tagValue}>{row.priceRef ? "≈$" : "$"}</span>
            <span style={tagValue}>
              {Fmt.g2(row.pin)}/{Fmt.g2(row.pout)}
            </span>
            {row.pcr > 0 && (
              <>
                <span style={{ ...tagValue, opacity: 0.6 }}>·</span>
                <span style={tagLabel}>{L("读")}</span>
                <span style={tagValue}>{Fmt.g2(row.pcr)}</span>
              </>
            )}
          </TintTag>
        )}
      </div>
    </div>
  );
}

/** 「按模型 (N)」开关 + 展开后的模型列表。 */
export function ModelDisclosure({
  rows,
  tint,
  periodLabel,
  defaultOpen = false,
}: {
  rows: ModelRow[];
  tint: RGB;
  periodLabel: string;
  defaultOpen?: boolean;
}) {
  const [open, setOpen] = useState(defaultOpen);
  const [expanded, setExpanded] = useState<Set<string>>(new Set());
  const toggle = (id: string) =>
    setExpanded((current) => {
      const next = new Set(current);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  return (
    <>
      <Disclosure open={open} onToggle={() => setOpen((v) => !v)} label={L("按模型 (%@)", rows.length)} tint={tint} />
      {open && (
        <div style={{ padding: 10, borderRadius: 7, background: fill(0.05), display: "flex", flexDirection: "column", gap: 6 }}>
          <span style={{ fontSize: fs(11), fontWeight: 600, color: T.secondary }}>{L("按模型 · %@", periodLabel)}</span>
          {rows.map((row) => {
            const isExpanded = expanded.has(row.id);
            return (
              <div key={row.id} style={{ display: "flex", flexDirection: "column" }}>
                <button
                  className="plain"
                  onClick={() => row.hasBreakdown && toggle(row.id)}
                  style={{ display: "flex", alignItems: "flex-start", gap: 7, width: "100%", cursor: row.hasBreakdown ? "pointer" : "default" }}
                >
                  <span style={{ width: 8, height: 16, display: "grid", placeItems: "center", flex: "none" }}>
                    {row.hasBreakdown && (
                      <Icon name={isExpanded ? "chevron.down" : "chevron.right"} size={fs(8)} color={T.tertiary} strokeWidth={3} />
                    )}
                  </span>
                  <span style={{ width: 5, height: 5, borderRadius: 3, background: rgba(tint, 0.7), marginTop: 6, flex: "none" }} />
                  <span style={{ fontSize: fs(11.5), color: T.primary, textAlign: "left", minWidth: 0, overflowWrap: "anywhere" }}>
                    {data(row.name)}
                  </span>
                  <Spacer />
                  <HStack gap={6} style={{ flex: "none" }}>
                    {row.total > 0 && <span style={{ fontSize: fs(9.5), fontFamily: MONO, color: T.secondary }}>{Fmt.human(row.total)}</span>}
                    {row.hit > 0 && (
                      <span
                        style={{ fontSize: fs(9.5), fontFamily: MONO, color: T.secondary, padding: "1px 4px", borderRadius: 999, background: fill(0.06) }}
                      >
                        {row.hit.toFixed(0)}%
                      </span>
                    )}
                    {(row.cost > 0 || (row.costCny ?? 0) > 0) && (
                      <span style={{ fontSize: fs(11.5), fontWeight: 600, fontFamily: MONO, color: T.primary }}>
                        {Fmt.nativeMoney(row.cost, row.costCny)}
                      </span>
                    )}
                    {(row.credits ?? 0) > 0 && (
                      <span style={{ fontSize: fs(11.5), fontWeight: 600, fontFamily: MONO, color: T.primary }}>
                        {Fmt.credits(row.credits ?? 0)} C
                      </span>
                    )}
                  </HStack>
                </button>
                {isExpanded && row.hasBreakdown && <ModelDetailRow row={row} tint={tint} />}
              </div>
            );
          })}
        </div>
      )}
    </>
  );
}

export function tokenModelHit(m: TokenModelStat): number {
  const denom = (m.cr ?? 0) + (m.cw ?? 0) + m.in;
  return denom > 0 ? ((m.cr ?? 0) / denom) * 100 : 0;
}

export function tokenModelTotal(m: TokenModelStat, reasonIncludedInOutput = false): number {
  if (m.tokens && m.tokens > 0) return m.tokens;
  return m.in + m.out + (m.cr ?? 0) + (m.cw ?? 0) + (reasonIncludedInOutput ? 0 : (m.reason ?? 0));
}

/** TokenModelStat 列表转成明细行（tokenModelDisclosure 的口径）。 */
export function tokenModelRows(
  models: TokenModelStat[],
  { reasonIncludedInOutput = false, inclusiveIO = false, perf }: { reasonIncludedInOutput?: boolean; inclusiveIO?: boolean; perf?: PerfStat | null } = {},
): ModelRow[] {
  return models.map((m) => {
    const cr = m.cr ?? 0;
    const cw = m.cw ?? 0;
    const reason = m.reason ?? 0;
    return {
      id: m.model_id ?? m.name,
      name: m.name,
      pin: m.pin ?? 0,
      pout: m.pout ?? 0,
      pcr: m.pcr ?? 0,
      cost: m.cost ?? 0,
      costCny: m.cost_cny,
      credits: m.credits ?? 0,
      total: tokenModelTotal(m, reasonIncludedInOutput),
      hit: tokenModelHit(m),
      tokIn: inclusiveIO ? m.in + cr + cw : m.in,
      tokOut: inclusiveIO ? m.out + reason : m.out,
      tokCR: cr,
      tokCW: cw,
      tokReason: reason,
      componentsAreSubtotals: inclusiveIO,
      priceRef: m.pref,
      perf: modelPerf(perf, m.name),
      hasBreakdown:
        m.in + m.out + cr + cw + reason > 0 || (m.cost ?? 0) > 0 || (m.credits ?? 0) > 0 || (m.pin ?? 0) > 0 || (m.pout ?? 0) > 0,
    };
  });
}
