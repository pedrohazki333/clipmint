"use client";

import { getClipWatermarkUrl, getWatermarkUrl } from "@/lib/api";
import type { BrandDraft, FontOption } from "@/lib/brand";
import type { SourceType } from "@/lib/types";

import BannerColorSettings from "@/components/BannerColorSettings";
import BarStyleSettings from "@/components/BarStyleSettings";
import ClipWatermarkSettings from "@/components/ClipWatermarkSettings";
import WatermarkSettings from "@/components/WatermarkSettings";

/**
 * A marca do perfil, reunida — e agora DENTRO do formulário.
 *
 * Os quatro painéis viraram campos controlados de um rascunho só
 * (`lib/brand.ts`), gravado pelo botão "Salvar alterações" junto com o resto do
 * perfil. Antes cada um salvava sozinho, o que obrigava a marca a existir só
 * depois de o perfil ser criado e enchia a tela de botões de salvar.
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
    <div className="border-t border-line pt-6">
      <p className="mb-1 text-body font-medium text-ink">Marca</p>
      <p className="mb-4 text-label text-ink-muted">
        A identidade que o clipe carrega. Vale só para este perfil, e é salva
        junto com ele.
      </p>

      <div className="flex flex-col gap-6">
        <WatermarkSettings
          value={draft.watermark}
          onChange={(watermark) => onChange({ ...draft, watermark })}
          savedUrl={profileId ? getWatermarkUrl(escopo) : undefined}
          disabled={disabled}
        />
        <ClipWatermarkSettings
          value={draft.clipWatermark}
          onChange={(clipWatermark) => onChange({ ...draft, clipWatermark })}
          savedUrl={profileId ? getClipWatermarkUrl(escopo) : undefined}
          disabled={disabled}
        />
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
      </div>
    </div>
  );
}
