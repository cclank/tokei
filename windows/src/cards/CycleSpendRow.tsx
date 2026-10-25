import * as Fmt from "../lib/fmt";
import { L } from "../lib/i18n";
import { currentCycle, cycleCostLabel, type QuotaDetailPayload } from "../lib/quotaDetail";
import { HStack, Spacer, Tip } from "../ui/kit";
import { fs, T } from "../ui/theme";

export function CycleSpendRow({ payload, tool, reset }: { payload?: QuotaDetailPayload | null; tool: string; reset?: number | null }) {
  const cycle = currentCycle(payload, tool, reset);
  const cost = cycle && cycleCostLabel(cycle);
  if (!cycle || cost == null) return null;
  return (
    <Tip text={Fmt.reset(cycle.start) + " → " + L("上次额度重置到现在，所有设备合计，按 API 价折算")}>
    <HStack gap={5} style={{ flexWrap: "nowrap" }}>
      <span style={{ fontSize: fs(11), color: T.secondary, whiteSpace: "nowrap", flex: "none" }}>{L("本周期已花")}</span>
      <span style={{ fontSize: fs(9.5), fontFamily: "var(--mono)", color: T.tertiary, whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>{L("自 %@", Fmt.day(cycle.start))}</span>
      <Spacer />
      <span style={{ fontSize: fs(12), fontWeight: 600, fontFamily: "var(--mono)", color: T.primary, whiteSpace: "nowrap", flex: "none" }}>≈ {cost}</span>
      <span style={{ fontSize: fs(9.5), fontFamily: "var(--mono)", color: T.tertiary, whiteSpace: "nowrap", flex: "none" }}>· {cycle.approx ? "≈" : ""}{Fmt.human(cycle.tokens)}</span>
    </HStack>
    </Tip>
  );
}
