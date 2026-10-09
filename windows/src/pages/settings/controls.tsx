// 设置页的复用部件，逐个对应 Mac 版 PanelView 的 settingsSection / settingsActionButton /
// settingsToggleRow / settingsStackedValue / settingsRow / providerSettingsField。
import { useLayoutEffect, useRef, useState, type CSSProperties, type ReactNode } from "react";
import {
  ALargeSmall,
  Bug,
  CircleCheck,
  CircleChevronUp,
  Cog,
  Grid2x2,
  KeyRound,
  PanelTop,
  Search,
  Stethoscope,
  type LucideIcon,
} from "lucide-react";
import { Icon } from "../../ui/Icon";
import { fill, fs, gradient, rgba, T, Theme, type RGB } from "../../ui/theme";
import "./settings.css";

/** Icon.tsx 里没有的 SF Symbols，设置页自己映射。 */
const EXTRA_ICONS: Record<string, LucideIcon> = {
  "textformat.size": ALargeSmall,
  "menubar.rectangle": PanelTop,
  "gearshape.2": Cog,
  "square.grid.2x2": Grid2x2,
  "key.horizontal.fill": KeyRound,
  stethoscope: Stethoscope,
  ladybug: Bug,
  "chevron.up.circle": CircleChevronUp,
  "checkmark.circle": CircleCheck,
  "magnifyingglass.circle": Search,
};

export function SIcon({ name, size, color, strokeWidth = 2.2 }: { name: string; size: number; color?: string; strokeWidth?: number }) {
  const Extra = EXTRA_ICONS[name];
  if (Extra) return <Extra size={size} color={color ?? "currentColor"} strokeWidth={strokeWidth} style={{ flex: "none" }} />;
  return <Icon name={name} size={size} color={color} strokeWidth={strokeWidth} style={{ flex: "none" }} />;
}

/** 一块设置：圆底图标 + 标题，下面是内容（settingsSection）。 */
export function SettingsSection({ icon, title, children }: { icon: string; title: string; children: ReactNode }) {
  return (
    <div
      style={{
        display: "flex",
        flexDirection: "column",
        gap: 8,
        padding: 10,
        borderRadius: 9,
        background: "rgba(0, 0, 0, 0.16)",
        boxShadow: "inset 0 0 0 0.7px rgba(255, 255, 255, 0.06)",
        minWidth: 0,
      }}
    >
      <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
        <span
          style={{
            width: 20,
            height: 20,
            borderRadius: 10,
            display: "grid",
            placeItems: "center",
            flex: "none",
            background: rgba(Theme.claude, 0.1),
            color: rgba(Theme.claude, 0.95),
          }}
        >
          <SIcon name={icon} size={fs(10)} strokeWidth={2.6} />
        </span>
        <span style={{ fontSize: fs(12), fontWeight: 600, color: T.secondary }}>{title}</span>
      </div>
      <div style={{ display: "flex", flexDirection: "column", gap: 6, minWidth: 0 }}>{children}</div>
    </div>
  );
}

export function ActionButton({
  icon,
  title,
  onClick,
  disabled = false,
}: {
  icon: string;
  title: string;
  onClick: () => void;
  disabled?: boolean;
}) {
  return (
    <button className="st-action" onClick={onClick} disabled={disabled}>
      <SIcon name={icon} size={fs(9)} />
      <span style={{ fontSize: fs(10), fontWeight: 500 }}>{title}</span>
    </button>
  );
}

export function Switch({
  on,
  onChange,
  label,
  disabled = false,
}: {
  on: boolean;
  onChange: (next: boolean) => void;
  label: string;
  disabled?: boolean;
}) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={on}
      aria-label={label}
      className={`st-switch${on ? " on" : ""}`}
      disabled={disabled}
      onClick={() => onChange(!on)}
    />
  );
}

/** 标题 + 开关的一整行（settingsToggleRow）。 */
export function ToggleRow({
  title,
  on,
  onChange,
  disabled = false,
}: {
  title: string;
  on: boolean;
  onChange: (next: boolean) => void;
  disabled?: boolean;
}) {
  return (
    <div
      style={{
        display: "flex",
        alignItems: "center",
        gap: 8,
        padding: "7px 10px",
        borderRadius: 8,
        background: fill(0.04),
      }}
    >
      <span style={{ flex: 1, minWidth: 0, fontSize: fs(11), color: T.primary }}>{title}</span>
      <Switch on={on} onChange={onChange} label={title} disabled={disabled} />
    </div>
  );
}

/** 「显示卡片」「额度来源」网格里的一格：色点 + 名称 + 开关（settingsRow）。 */
export function TintToggleRow({
  name,
  tint,
  on,
  onChange,
}: {
  name: string;
  tint: RGB;
  on: boolean;
  onChange: (next: boolean) => void;
}) {
  return (
    <div
      style={{
        display: "flex",
        alignItems: "center",
        gap: 6,
        height: 34,
        padding: "0 8px",
        borderRadius: 7,
        background: fill(0.04),
        minWidth: 0,
      }}
    >
      <span
        style={{
          width: 6,
          height: 6,
          borderRadius: 3,
          flex: "none",
          background: gradient(tint),
          boxShadow: `0 0 2px ${rgba(tint, 0.4)}`,
        }}
      />
      <FitText text={name} size={fs(11)} />
      <Switch on={on} onChange={onChange} label={name} />
    </div>
  );
}

/** 一行放不下时先缩小字号（最小 0.72 倍，同 minimumScaleFactor），再放不下才省略。 */
function FitText({ text, size }: { text: string; size: number }) {
  const box = useRef<HTMLSpanElement>(null);
  const inner = useRef<HTMLSpanElement>(null);
  const [scale, setScale] = useState(1);
  const scaleRef = useRef(1);
  useLayoutEffect(() => {
    const outer = box.current;
    const content = inner.current;
    if (!outer || !content) return;
    const fit = () => {
      const natural = content.offsetWidth / scaleRef.current;
      const available = outer.clientWidth;
      const next = natural > 0 && available > 0 ? Math.max(0.72, Math.min(1, available / natural)) : 1;
      if (Math.abs(next - scaleRef.current) > 0.005) {
        scaleRef.current = next;
        setScale(next);
      }
    };
    fit();
    const observer = new ResizeObserver(fit);
    observer.observe(outer);
    return () => observer.disconnect();
  }, [text, size]);
  return (
    <span
      ref={box}
      title={text}
      style={{
        flex: 1,
        minWidth: 0,
        overflow: "hidden",
        textOverflow: "ellipsis",
        whiteSpace: "nowrap",
        fontSize: size * scale,
        fontWeight: 500,
        color: T.primary,
      }}
    >
      <span ref={inner}>{text}</span>
    </span>
  );
}

export function ToggleGrid({ children }: { children: ReactNode }) {
  return <div style={{ display: "grid", gridTemplateColumns: "minmax(0, 1fr) minmax(0, 1fr)", gap: 7 }}>{children}</div>;
}

/** 小标题在上、控件在下（settingsStackedValue）。 */
export function StackedValue({ title, children }: { title: string; children: ReactNode }) {
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 5, padding: "5px 10px", minWidth: 0 }}>
      <span style={{ fontSize: fs(10), color: T.tertiary }}>{title}</span>
      {children}
    </div>
  );
}

/** 迷你分段控件（.pickerStyle(.segmented).controlSize(.mini)）。 */
export function Segmented<V extends string>({
  value,
  options,
  onChange,
  label,
  fontSize = 10,
  style,
}: {
  value: V;
  options: { value: V; label: string }[];
  onChange: (value: V) => void;
  label: string;
  fontSize?: number;
  style?: CSSProperties;
}) {
  return (
    <div className="segmented st-segmented" role="radiogroup" aria-label={label} style={{ background: fill(0.06), ...style }}>
      {options.map((option) => (
        <button
          key={option.value}
          role="radio"
          aria-checked={option.value === value}
          className={`segment${option.value === value ? " on" : ""}`}
          style={{ fontSize: fs(fontSize) }}
          onClick={() => onChange(option.value)}
        >
          {option.label}
        </button>
      ))}
    </div>
  );
}

/** 说明文字：8.5 号、三级灰，可以折行。 */
export function Note({ children, size = 8.5, color = T.tertiary }: { children: ReactNode; size?: number; color?: string }) {
  return <span style={{ fontSize: fs(size), color, lineHeight: 1.35 }}>{children}</span>;
}

/** Provider 的输入框：左边 52 宽的标签，右边等宽字体输入（providerSettingsField）。 */
export function ProviderField({
  label,
  placeholder,
  value,
  onChange,
  secure = false,
}: {
  label: string;
  placeholder: string;
  value: string;
  onChange: (value: string) => void;
  secure?: boolean;
}) {
  return (
    <div style={{ display: "flex", alignItems: "center", gap: 8, minWidth: 0 }}>
      <span style={{ width: 52, flex: "none", fontSize: fs(9.5), color: T.tertiary }}>{label}</span>
      <input
        className="st-input"
        type={secure ? "password" : "text"}
        value={value}
        placeholder={placeholder}
        aria-label={label}
        spellCheck={false}
        autoComplete="off"
        autoCapitalize="off"
        autoCorrect="off"
        onChange={(event) => onChange(event.target.value)}
        style={{ fontSize: fs(9.5) }}
      />
    </div>
  );
}

/** ProgressView().controlSize(.mini)。 */
export function MiniSpinner() {
  return <span className="spinner" style={{ width: 11, height: 11, borderWidth: 1.5, flex: "none" }} />;
}
