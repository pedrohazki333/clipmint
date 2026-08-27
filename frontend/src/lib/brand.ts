/**
 * O rascunho de marca de um perfil.
 *
 * Antes cada painel de marca falava com a API sozinho e salvava no ato. Isso
 * dava dois problemas: a marca só podia ser configurada DEPOIS de criar o
 * perfil (os presets são gravados numa pasta com o id dele), e a tela de edição
 * tinha um botão de salvar por painel além do "Salvar alterações" do
 * formulário — quatro botões prometendo coisas diferentes.
 *
 * Aqui a marca vira estado comum de formulário: os painéis só leem e escrevem
 * este objeto, e quem grava é `applyBrandDraft`, chamado uma vez no submit —
 * depois de criar o perfil, quando é criação. Um botão, uma promessa.
 */

import {
  deleteClipWatermark,
  deleteWatermark,
  getBannerColors,
  getBarStyle,
  hasClipWatermark,
  hasWatermark,
  resetBannerColors,
  resetBarStyle,
  saveBannerColors,
  saveBarStyle,
  uploadClipWatermark,
  uploadWatermark,
} from "@/lib/api";
import {
  BANNER_DEFAULT_BG,
  BANNER_DEFAULT_TEXT,
  BAR_DEFAULT_BG,
  BAR_DEFAULT_TEXT,
} from "@/lib/branding";
import { DEFAULT_FONT } from "@/components/FontField";
import type { SourceType } from "@/lib/types";

export type Escopo = { source: SourceType; profileId?: string };

/** Uma imagem do preset: a que está salva, a escolhida agora, e o pedido de tirar. */
export interface FileSlot {
  /** Já existe imagem gravada neste escopo. */
  saved: boolean;
  /** Escolhida agora no seletor, ainda não enviada. */
  file: File | null;
  /** Pedido de remover a que está salva. */
  remove: boolean;
}

export interface BannerDraft {
  bg: string;
  text: string;
  font: string;
}

export interface BarDraft extends BannerDraft {
  name: string;
}

export interface BrandDraft {
  banner: BannerDraft;
  bar: BarDraft;
  watermark: FileSlot;
  clipWatermark: FileSlot;
}

/** Fontes que o servidor oferece, para os dois seletores. */
export type FontOption = { key: string; label: string };

const SLOT_VAZIO: FileSlot = { saved: false, file: null, remove: false };

export const BANNER_PADRAO: BannerDraft = {
  bg: BANNER_DEFAULT_BG,
  text: BANNER_DEFAULT_TEXT,
  font: DEFAULT_FONT,
};

export const BAR_PADRAO: BarDraft = {
  bg: BAR_DEFAULT_BG,
  text: BAR_DEFAULT_TEXT,
  font: DEFAULT_FONT,
  name: "",
};

/** O rascunho de um perfil que ainda não existe: tudo no padrão do ClipMint. */
export function draftPadrao(): BrandDraft {
  return {
    banner: { ...BANNER_PADRAO },
    bar: { ...BAR_PADRAO },
    watermark: { ...SLOT_VAZIO },
    clipWatermark: { ...SLOT_VAZIO },
  };
}

export interface BrandSnapshot {
  draft: BrandDraft;
  fonts: FontOption[];
  /** O perfil já tinha estilo próprio gravado (não é o padrão herdado). */
  bannerCustomizado: boolean;
  barCustomizado: boolean;
}

/**
 * Lê o que está valendo para este escopo.
 *
 * Falha de rede não derruba o formulário: sem resposta, o rascunho fica no
 * padrão do produto — que é o mesmo que o clipe usaria.
 */
export async function loadBrandDraft(escopo: Escopo): Promise<BrandSnapshot> {
  const draft = draftPadrao();
  let fonts: FontOption[] = [];
  let bannerCustomizado = false;
  let barCustomizado = false;

  const [banner, bar, temLogo, temArte] = await Promise.all([
    getBannerColors(escopo).catch(() => null),
    getBarStyle(escopo).catch(() => null),
    hasWatermark(escopo).catch(() => false),
    hasClipWatermark(escopo).catch(() => false),
  ]);

  if (banner) {
    draft.banner = {
      bg: banner.bg_color,
      text: banner.text_color,
      font: banner.font,
    };
    fonts = banner.available_fonts;
    bannerCustomizado = banner.customized;
  }
  if (bar) {
    draft.bar = {
      bg: bar.bg_color,
      text: bar.text_color,
      font: bar.font,
      name: bar.name,
    };
    if (fonts.length === 0) fonts = bar.available_fonts;
    barCustomizado = bar.customized;
  }
  draft.watermark.saved = temLogo;
  draft.clipWatermark.saved = temArte;

  return { draft, fonts, bannerCustomizado, barCustomizado };
}

function igual(a: object, b: object): boolean {
  return JSON.stringify(a) === JSON.stringify(b);
}

/**
 * Grava o rascunho.
 *
 * Só toca no que mudou, e trata "voltou a ser exatamente o padrão" como
 * remoção do preset — que é o que o botão "Restaurar padrão" sempre fez. O
 * resultado no clipe é o mesmo dos dois jeitos; apagar deixa o perfil sem
 * arquivo em vez de com um arquivo que repete o default.
 *
 * Erro aqui NÃO é silencioso: sobe para o formulário, que já salvou o perfil e
 * precisa dizer qual metade não foi.
 */
export async function applyBrandDraft(
  escopo: Escopo,
  draft: BrandDraft,
  base: BrandSnapshot,
): Promise<void> {
  // Imagens primeiro: são o que a pessoa vê no clipe e o que mais falha
  // (arquivo grande, formato recusado).
  if (draft.watermark.remove && base.draft.watermark.saved) {
    await deleteWatermark(escopo);
  } else if (draft.watermark.file) {
    await uploadWatermark(escopo, draft.watermark.file);
  }

  if (draft.clipWatermark.remove && base.draft.clipWatermark.saved) {
    await deleteClipWatermark(escopo);
  } else if (draft.clipWatermark.file) {
    await uploadClipWatermark(escopo, draft.clipWatermark.file);
  }

  const bannerMudou = !igual(draft.banner, base.draft.banner);
  if (bannerMudou) {
    if (igual(draft.banner, BANNER_PADRAO)) {
      if (base.bannerCustomizado) await resetBannerColors(escopo);
    } else {
      await saveBannerColors(escopo, draft.banner.bg, draft.banner.text, draft.banner.font);
    }
  }

  const barMudou = !igual(draft.bar, base.draft.bar);
  if (barMudou) {
    if (igual(draft.bar, BAR_PADRAO)) {
      if (base.barCustomizado) await resetBarStyle(escopo);
    } else {
      await saveBarStyle(
        escopo,
        draft.bar.bg,
        draft.bar.text,
        draft.bar.font,
        draft.bar.name,
      );
    }
  }
}

/** Tem alguma coisa para gravar? Serve para não chamar a API à toa. */
export function brandSujo(draft: BrandDraft, base: BrandSnapshot): boolean {
  return (
    !igual(draft.banner, base.draft.banner) ||
    !igual(draft.bar, base.draft.bar) ||
    draft.watermark.file !== null ||
    draft.clipWatermark.file !== null ||
    (draft.watermark.remove && base.draft.watermark.saved) ||
    (draft.clipWatermark.remove && base.draft.clipWatermark.saved)
  );
}
