"use client";

import { getClipWatermarkUrl, getWatermarkUrl } from "@/lib/api";
import type { BrandDraft, FontOption } from "@/lib/brand";
import type { SourceType } from "@/lib/types";

import BannerColorSettings from "@/components/BannerColorSettings";
import BarStyleSettings from "@/components/BarStyleSettings";
import ClipWatermarkSettings from "@/components/ClipWatermarkSettings";
import WatermarkSettings from "@/components/WatermarkSettings";
import { SectionCard } from "@/components/ui";

/**
 * A marca do perfil, em três blocos.
 *
 * Os quatro painéis viraram campos controlados de um rascunho só
 * (`lib/brand.ts`), gravado pelo botão "Salvar alterações" junto com o resto do
 * perfil. Antes cada um salvava sozinho, o que obrigava a marca a existir só
 * depois de o perfil ser criado e enchia a tela de botões de salvar.
 *
 * Os quatro não viraram quatro cartões: as duas imagens andam juntas — são a
 * mesma decisão ("que arte é sua") tomada para dois lugares do clipe — e ficam
 * lado a lado justamente para deixar visível que são arquivos diferentes. Cor e
 * fonte, que se ajustam olhando a prévia, ganham cartão próprio cada.
 *
 * Sem `profileId` (criação) não há imagem gravada para mostrar: a prévia é a do
 * arquivo escolhido, que sobe quando o perfil nascer.
 */
export default function BrandSettings({
  source,
  profileId,
  draft,
  onChange,
  fonts,
  disabled,
}: {
  source: SourceType;
  profileId?: string;
  draft: BrandDraft;
  onChange: (v: BrandDraft) => void;
  fonts: FontOption[];
  disabled?: boolean;
}) {
  const escopo = { source, profileId };

  return (
    <>
      <SectionCard
        icon="marca"
        title="Suas imagens"
        description="Duas artes, dois papéis: uma tapa o que não é seu, a outra assina o que é."
      >
        <WatermarkSettings
          value={draft.watermark}
          onChange={(watermark) => onChange({ ...draft, watermark })}
          savedUrl={profileId ? getWatermarkUrl(escopo) : undefined}
          disabled={disabled}
        />
        <div className="border-t border-line pt-4">
          <ClipWatermarkSettings
            value={draft.clipWatermark}
            onChange={(clipWatermark) => onChange({ ...draft, clipWatermark })}
            savedUrl={profileId ? getClipWatermarkUrl(escopo) : undefined}
            disabled={disabled}
          />
        </div>
      </SectionCard>

      <BannerColorSettings
        value={draft.banner}
        onChange={(banner) => onChange({ ...draft, banner })}
        fonts={fonts}
        disabled={disabled}
      />

      <BarStyleSettings
        value={draft.bar}
        onChange={(bar) => onChange({ ...draft, bar })}
        fonts={fonts}
        disabled={disabled}
      />
    </>
  );
}
