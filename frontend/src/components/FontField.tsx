"use client";

/**
 * Escolha da família de fonte usada no render (banner e faixa).
 *
 * A lista de famílias vem do backend porque depende de quais fontes estão
 * instaladas na máquina que renderiza — oferecer uma que não existe lá daria
 * um clipe com a fonte trocada sem nenhum aviso.
 */

export const DEFAULT_FONT = "condensed";

/**
 * Aproximação em CSS das fontes que o backend usa no render. O preview serve
 * para julgar peso e proporção; a fonte final é a instalada no servidor.
 */
export const FONT_STACKS: Record<string, { family: string; weight: number }> = {
  condensed: { family: "'DejaVu Sans Condensed', 'Arial Narrow', sans-serif", weight: 700 },
  sans: { family: "'DejaVu Sans', Arial, sans-serif", weight: 700 },
  inter: { family: "Inter, system-ui, sans-serif", weight: 700 },
  inter_black: { family: "Inter, system-ui, sans-serif", weight: 900 },
  montserrat: { family: "Montserrat, system-ui, sans-serif", weight: 700 },
  montserrat_black: { family: "Montserrat, system-ui, sans-serif", weight: 900 },
  serif: { family: "'DejaVu Serif', Georgia, serif", weight: 700 },
  mono: { family: "'DejaVu Sans Mono', monospace", weight: 700 },
};

export function fontStack(key: string) {
  return FONT_STACKS[key] ?? FONT_STACKS[DEFAULT_FONT];
}

interface Props {
  value: string;
  onChange: (v: string) => void;
  disabled: boolean;
  /** Famílias instaladas no backend; vazio = só o padrão. */
  fonts: { key: string; label: string }[];
  label?: string;
}

export default function FontField({ value, onChange, disabled, fonts, label = "Família" }: Props) {
  const options = fonts.length ? fonts : [{ key: DEFAULT_FONT, label: "Padrão" }];
  return (
    <div className="flex items-center gap-2">
      <span className="text-label text-ink-dim">{label}</span>
      <select
        value={value}
        disabled={disabled || fonts.length === 0}
        onChange={(e) => onChange(e.target.value)}
        className="rounded-sm bg-inset border border-line px-2 py-1.5 text-body text-ink outline-none focus:border-mint disabled:opacity-50"
      >
        {options.map((f) => (
          <option key={f.key} value={f.key}>
            {f.label}
          </option>
        ))}
      </select>
    </div>
  );
}
