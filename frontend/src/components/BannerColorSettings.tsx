"use client";

import ColorField, { HEX_RE, toFullHex } from "@/components/ColorField";
import FontField, { fontStack } from "@/components/FontField";
import { BANNER_PADRAO, type BannerDraft, type FontOption } from "@/lib/brand";
import {
  BANNER_DEFAULT_BG as DEFAULT_BG,
  BANNER_DEFAULT_TEXT as DEFAULT_TEXT,
} from "@/lib/branding";

/**
 * Cores e fonte do banner de título — campo controlado.
 *
 * O preview desenha o que o FFmpeg vai desenhar; os defaults vêm de
 * `lib/branding.ts`, que é espelho de `layout.py`.
 */
interface Props {
  value: BannerDraft;
  onChange: (v: BannerDraft) => void;
  fonts: FontOption[];
  disabled?: boolean;
}

export function bannerValido(v: BannerDraft): boolean {
  return HEX_RE.test(v.bg) && HEX_RE.test(v.text);
}

export default function BannerColorSettings({
  value,
  onChange,
  fonts,
  disabled = false,
}: Props) {
  const previewBg = toFullHex(value.bg, DEFAULT_BG);
  const previewText = toFullHex(value.text, DEFAULT_TEXT);
  const stack = fontStack(value.font);
  const noPadrao =
    value.bg === BANNER_PADRAO.bg &&
    value.text === BANNER_PADRAO.text &&
    value.font === BANNER_PADRAO.font;

  return (
    <div className="flex flex-col gap-3">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <p className="text-body font-medium text-ink">Banner de título</p>
          <p className="mt-1 text-label text-ink-muted">
            Cores e fonte da faixa de título nos próximos clipes.
          </p>
        </div>
        {!noPadrao && (
          <button
            type="button"
            disabled={disabled}
            onClick={() => onChange({ ...BANNER_PADRAO })}
            className="text-label text-ink-dim transition-colors hover:text-ink disabled:opacity-50"
          >
            Restaurar padrão
          </button>
        )}
      </div>

      {/* Preview: retângulo de ponta a ponta, como sai no clipe */}
      <div
        className="select-none overflow-hidden rounded px-5 py-3 text-center"
        style={{ backgroundColor: previewBg }}
      >
        <span
          className="text-body"
          style={{
            color: previewText,
            fontFamily: stack.family,
            fontWeight: stack.weight,
          }}
        >
          TÍTULO DO CLIP
        </span>
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
      </div>

      {!bannerValido(value) && (
        <p className="rounded-sm bg-amber-900/15 px-3 py-2 text-label text-amber-500/80">
          Use hexadecimal no formato #RRGGBB (ex: {DEFAULT_BG}).
        </p>
      )}
    </div>
  );
}
