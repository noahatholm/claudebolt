// Small shared controls. Styling lives in styles.css.
import { useEffect, type ReactNode } from "react";
import { Icon, type IconName } from "./Icon";

export function Segmented<T extends string>({
  value, options, onChange, full, iconOnly,
}: {
  value: T;
  options: { value: T; label: string; icon?: IconName; hint?: string }[];
  onChange: (v: T) => void;
  full?: boolean;
  iconOnly?: boolean;
}) {
  return (
    <div className={`segmented${full ? " full" : ""}${iconOnly ? " icons" : ""}`} role="radiogroup">
      {options.map((o) => (
        <button
          key={o.value}
          type="button"
          role="radio"
          aria-checked={o.value === value}
          aria-label={o.label}
          title={o.hint ?? o.label}
          className={o.value === value ? "on" : ""}
          onClick={() => onChange(o.value)}
        >
          {o.icon && <Icon name={o.icon} size={14} />}
          {!iconOnly && o.label}
        </button>
      ))}
    </div>
  );
}

export function NumField({
  label, value, onChange, step, min, suffix, hint,
}: {
  label: string;
  value: number;
  onChange: (v: number) => void;
  step: number;
  min?: number;
  suffix?: string;
  hint?: string;
}) {
  return (
    <label className="field" title={hint}>
      <span>{label}</span>
      <div className="num">
        <input className="input" type="number" step={step} min={min} value={value} onChange={(e) => onChange(parseFloat(e.target.value))} />
        {suffix && <em>{suffix}</em>}
      </div>
    </label>
  );
}

export function Switch({ checked, onChange, children }: { checked: boolean; onChange: (v: boolean) => void; children: ReactNode }) {
  return (
    <label className="switch">
      <input type="checkbox" checked={checked} onChange={(e) => onChange(e.target.checked)} />
      <span className="grow">{children}</span>
    </label>
  );
}

export function Progress({ value }: { value: number }) {
  return (
    <div className="progress" role="progressbar" aria-valuenow={Math.round(value * 100)} aria-valuemin={0} aria-valuemax={100}>
      <i style={{ width: `${Math.max(2, Math.round(value * 100))}%` }} />
    </div>
  );
}

export function Notice({ tone = "warn", children }: { tone?: "warn" | "error" | "ok"; children: ReactNode }) {
  return (
    <div className={`notice ${tone}`}>
      <Icon name={tone === "ok" ? "check" : "alert"} size={14} />
      <span className="grow">{children}</span>
    </div>
  );
}

export function Modal({
  title, subtitle, onClose, children, footer, width,
}: {
  title: string;
  subtitle?: string;
  onClose: () => void;
  children: ReactNode;
  footer?: ReactNode;
  width?: number;
}) {
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);
  return (
    <div className="modal" onMouseDown={onClose}>
      <div className="dialog" style={{ width }} role="dialog" aria-modal aria-label={title} onMouseDown={(e) => e.stopPropagation()}>
        <header className="dialog-head">
          <div className="grow">
            <h2>{title}</h2>
            {subtitle && <p>{subtitle}</p>}
          </div>
          <button className="btn icon ghost" onClick={onClose} aria-label="Close">
            <Icon name="x" />
          </button>
        </header>
        <div className="dialog-body">{children}</div>
        {footer && <footer className="dialog-foot">{footer}</footer>}
      </div>
    </div>
  );
}
