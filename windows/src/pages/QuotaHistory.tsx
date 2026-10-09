// 待移植：占位页面。
import { L } from "../lib/i18n";
import { fs, T } from "../ui/theme";

export default function QuotaHistoryPage() {
  return <div style={{ padding: 24, textAlign: "center", color: T.tertiary, fontSize: fs(11) }}>{L("暂无数据")}</div>;
}
