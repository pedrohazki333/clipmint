"use client";

import { useId } from "react";

import ColorField, { HEX_RE, toFullHex } from "@/components/ColorField";
import FontField, { fontStack } from "@/components/FontField";
import { LinkButton, MiniField, SectionCard } from "@/components/ui";
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
  const nomeId = useId();
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
    <SectionCard
      icon="faixa"
      title="Faixa com o seu @"
      description="No modo facecam ela separa a câmera do jogo; na capa, fecha o banner."
      action={
        !noPadrao && (
          <LinkButton disabled={disabled} onClick={() => onChange({ ...BAR_PADRAO })}>
            Restaurar padrão
          </LinkButton>
        )
      }
    >
      {/* Preview da faixa em proporção parecida com a do clipe */}
      <div
        className="select-none overflow-hidden rounded-sm"
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

      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        <ColorField
          label="Fundo"
          value={value.bg}
          onChange={(bg) => onChange({ ...value, bg })}
          disabled={disabled}
          fallback={DEFAULT_BG}
        />
        <ColorField
          label="Texto"
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
        <MiniField label="Seu @" htmlFor={nomeId}>
          <input
            id={nomeId}
            type="text"
            value={value.name}
            disabled={disabled}
            maxLength={MAX_NAME}
            onChange={(e) => onChange({ ...value, name: e.target.value })}
            placeholder={BAR_DEFAULT_NAME}
            className="w-full min-w-0 rounded-sm border border-line bg-inset px-2 py-2 text-body text-ink outline-none transition-colors placeholder:text-ink-muted focus:border-mint disabled:opacity-50"
          />
        </MiniField>
      </div>

      <p className="text-label leading-relaxed text-ink-muted">
        Em branco, a faixa sai com <code>{BAR_DEFAULT_NAME}</code>. O preview
        aproxima a fonte com o que o navegador tem — o render usa a fonte
        instalada no servidor.
      </p>

      {!barValida(value) && (
        <p className="rounded-sm border border-danger/40 bg-danger-soft px-3 py-2 text-label text-danger">
          Use hexadecimal no formato #RRGGBB (ex: {DEFAULT_BG}).
        </p>
      )}
    </SectionCard>
  );
}
