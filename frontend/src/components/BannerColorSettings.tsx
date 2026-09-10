"use client";

import ColorField, { HEX_RE, toFullHex } from "@/components/ColorField";
import FontField, { fontStack } from "@/components/FontField";
import { LinkButton, SectionCard } from "@/components/ui";
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
    <SectionCard
      icon="banner"
      title="Banner de título"
      description="A faixa com a frase do corte, na emenda entre a capa e o vídeo."
      action={
        !noPadrao && (
          <LinkButton disabled={disabled} onClick={() => onChange({ ...BANNER_PADRAO })}>
            Restaurar padrão
          </LinkButton>
        )
      }
    >
      {/* Preview: retângulo de ponta a ponta, como sai no clipe */}
      <div
        className="select-none overflow-hidden rounded-sm px-5 py-3 text-center"
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
          TÍTULO DO CLIPE
        </span>
      </div>

      <div className="grid grid-cols-2 gap-3 sm:grid-cols-3">
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
        <p className="rounded-sm border border-danger/40 bg-danger-soft px-3 py-2 text-label text-danger">
          Use hexadecimal no formato #RRGGBB (ex: {DEFAULT_BG}).
        </p>
      )}
    </SectionCard>
  );
}
