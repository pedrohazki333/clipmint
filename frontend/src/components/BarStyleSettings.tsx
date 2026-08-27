"use client";

import ColorField, { HEX_RE, toFullHex } from "@/components/ColorField";
import FontField, { fontStack } from "@/components/FontField";
import { BAR_PADRAO, type BarDraft, type FontOption } from "@/lib/brand";
import {
  BAR_DEFAULT_BG as DEFAULT_BG,
  BAR_DEFAULT_NAME,
  BAR_DEFAULT_TEXT as DEFAULT_TEXT,
} from "@/lib/branding";

const MAX_NAME = 40;

/** Mistura duas cores hex (amount = quanto de fg). Espelha _mix() do backend. */
function mix(fg: string, bg: string, amount: number): string {
  const parse = (h: string) => [1, 3, 5].map((i) => parseInt(h.slice(i, i + 2), 16));
  const [fr, fgn, fb] = parse(fg);
  const [br, bgn, bb] = parse(bg);
  const ch = (f: number, b: number) =>
    Math.round(b + (f - b) * amount).toString(16).padStart(2, "0");
  return `#${ch(fr, br)}${ch(fgn, bgn)}${ch(fb, bb)}`;
}

interface Props {
  value: BarDraft;
  onChange: (v: BarDraft) => void;
  fonts: FontOption[];
  disabled?: boolean;
}

export function barValida(v: BarDraft): boolean {
  return HEX_RE.test(v.bg) && HEX_RE.test(v.text);
}

export default function BarStyleSettings({
  value,
  onChange,
  fonts,
  disabled = false,
}: Props) {
  const previewBg = toFullHex(value.bg, DEFAULT_BG);
  const previewText = toFullHex(value.text, DEFAULT_TEXT);
  const previewDot = mix(previewText, previewBg, 0.45);
  const previewHairline = mix(previewText, previewBg, 0.18);
  const stack = fontStack(value.font);
  // Sem nome preenchido a faixa escreve o padrão, e é ele que o preview mostra.
  const previewName = (value.name || BAR_DEFAULT_NAME).toUpperCase();
  const noPadrao =
    value.bg === BAR_PADRAO.bg &&
    value.text === BAR_PADRAO.text &&
    value.font === BAR_PADRAO.font &&
    value.name === BAR_PADRAO.name;

  return (
    <div className="flex flex-col gap-3">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <p className="text-body font-medium text-ink">Faixa com o nome</p>
          <p className="mt-1 text-label text-ink-muted">
            No streamer ela divide facecam e gameplay; no podcast fecha o banner.
            Sem nome, sai <code>{BAR_DEFAULT_NAME}</code>.
          </p>
        </div>
        {!noPadrao && (
          <button
            type="button"
            disabled={disabled}
            onClick={() => onChange({ ...BAR_PADRAO })}
            className="text-label text-ink-dim transition-colors hover:text-ink disabled:opacity-50"
          >
            Restaurar padrão
          </button>
        )}
      </div>

      {/* Preview da faixa em proporção parecida com a do clipe */}
      <div
        className="select-none overflow-hidden rounded"
        style={{
          backgroundColor: previewBg,
          borderTop: `1px solid ${previewHairline}`,
          borderBottom: `1px solid ${previewHairline}`,
        }}
      >
        <div
          className="flex items-center justify-center gap-6 whitespace-nowrap py-2.5 text-label"
          style={{
            color: previewText,
            fontFamily: stack.family,
            fontWeight: stack.weight,
            letterSpacing: "0.18em",
          }}
        >
          {Array.from({ length: 5 }).map((_, i) => (
            <span key={i} className="flex items-center gap-6">
              {previewName}
              {i < 4 && <span style={{ color: previewDot }}>•</span>}
            </span>
          ))}
        </div>
      </div>

      <div className="flex flex-wrap items-center gap-6">
        <ColorField
          label="Fundo"
          value={value.bg}
          onChange={(bg) => onChange({ ...value, bg })}
          disabled={disabled}
          fallback={DEFAULT_BG}
        />
        <ColorField
          label="Fonte"
          value={value.text}
          onChange={(text) => onChange({ ...value, text })}
          disabled={disabled}
          fallback={DEFAULT_TEXT}
        />
        <FontField
          value={value.font}
          onChange={(font: string) => onChange({ ...value, font })}
          disabled={disabled}
          fonts={fonts}
        />
        <div className="flex items-center gap-2">
          <span className="text-label text-ink-dim">Nome</span>
          <input
            type="text"
            value={value.name}
            disabled={disabled}
            maxLength={MAX_NAME}
            onChange={(e) => onChange({ ...value, name: e.target.value })}
            placeholder={BAR_DEFAULT_NAME}
            className="w-40 rounded-sm border border-line bg-inset px-2 py-1.5 text-body text-ink outline-none focus:border-mint disabled:opacity-50"
          />
        </div>
      </div>

      <p className="text-label text-ink-muted">
        O preview aproxima a fonte com o que o navegador tem — o render usa a
        fonte instalada no servidor.
      </p>

      {!barValida(value) && (
        <p className="rounded-sm bg-amber-900/15 px-3 py-2 text-label text-amber-500/80">
          Use hexadecimal no formato #RRGGBB (ex: {DEFAULT_BG}).
        </p>
      )}
    </div>
  );
}
