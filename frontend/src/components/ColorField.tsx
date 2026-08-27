"use client";

export const HEX_RE = /^#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{6})$/;

/** Expande #RGB para #RRGGBB (input type=color só aceita 6 dígitos). */
export function toFullHex(value: string, fallback: string): string {
  if (!HEX_RE.test(value)) return fallback;
  const v = value.slice(1);
  const full = v.length === 3 ? v.split("").map((c) => c + c).join("") : v;
  return `#${full.toUpperCase()}`;
}

interface Props {
  label: string;
  value: string;
  onChange: (v: string) => void;
  disabled: boolean;
  fallback: string;
}

/** Par seletor de cor + campo hexadecimal, usado nas configurações de marca. */
export default function ColorField({ label, value, onChange, disabled, fallback }: Props) {
  const valid = HEX_RE.test(value);
  return (
    <div className="flex items-center gap-2">
      <span className="text-label text-ink-dim w-16">{label}</span>
      <input
        type="color"
        value={toFullHex(value, fallback)}
        disabled={disabled}
        onChange={(e) => onChange(e.target.value.toUpperCase())}
        className="h-8 w-10 rounded cursor-pointer bg-transparent border border-line disabled:opacity-50"
      />
      <input
        type="text"
        value={value}
        disabled={disabled}
        onChange={(e) => onChange(e.target.value)}
        placeholder="#RRGGBB"
        maxLength={7}
        className={`w-24 rounded-sm bg-inset border px-2 py-1.5 text-body font-mono text-ink outline-none transition-colors ${
          valid ? "border-line focus:border-mint" : "border-red-700"
        }`}
      />
    </div>
  );
}
