/**
 * O estilo do clipe, do lado da tela.
 *
 * ESPELHO de `backend/app/clip_style.py` e das medidas de `services/title_card.py` e
 * `services/subtitler.py`. As duas cópias existem porque a prévia precisa responder na
 * hora, a cada cor escolhida, e o servidor é quem decide de verdade. Divergirem é bug:
 * a prévia mentiria sobre o clipe. `backend/tests/test_clip_style_parity.py` compara.
 */

export const DEFAULT_BRAND = "#FF395E";
export const INK = "#0B0B0C";
export const OUTLINE = "#000000";
export const WHITE = "#FFFFFF";
export const MIN_CONTRAST = 4.5;

export const PALETTE: Record<string, string> = {
  rosa: "#FF395E",
  amarelo: "#FFD23F",
  ciano: "#3EC8FF",
  verde: "#9DFF4F",
};

export const DEFAULT_FONT_KEY = "archivo";

/**
 * O centro da legenda, em pixels do quadro de 1080x1920. Os limites a mantêm fora do
 * topo e da base que a interface do TikTok cobre.
 */
export const CAPTION_Y_DEFAULT = 1205;
export const CAPTION_Y_MIN = 260;
export const CAPTION_Y_MAX = 1450;

/** Layouts em que a altura escolhida vale; os outros posicionam a legenda sozinhos. */
export function captionHeightApplies(layout: string): boolean {
  return layout !== "original" && layout !== "streamer";
}

export function clampCaptionY(y: number): number {
  return Math.round(Math.min(CAPTION_Y_MAX, Math.max(CAPTION_Y_MIN, y)));
}

export type CaptionEstilo = "caixa" | "cor";
export type CaptionTamanho = "P" | "M" | "G";

/** Layouts em que a arte da conta (marca d'água do clipe) pode entrar. */
export const WATERMARK_LAYOUTS = ["fullscreen", "cover", "crop", "original", "streamer"] as const;
export type WatermarkLayout = (typeof WATERMARK_LAYOUTS)[number];
export const WATERMARK_MIN_WIDTH = 0.05;
export const WATERMARK_MAX_WIDTH = 0.6;
export const WATERMARK_MIN_OPACITY = 0.1;

/** Onde a arte fica: centro e largura em frações do quadro, como o render usa. */
export interface WatermarkPlacement {
  ligado: boolean;
  x: number;
  y: number;
  largura: number;
  opacidade: number;
}

/** O padrão de cada layout: só o streamer começa com a arte, como era antes. */
export function defaultWatermark(layout: string): WatermarkPlacement {
  if (layout === "streamer") {
    return { ligado: true, x: 0.5, y: 0.794, largura: 0.185, opacidade: 0.7 };
  }
  return { ligado: false, x: 0.8, y: 0.12, largura: 0.185, opacidade: 0.7 };
}

/** A posição deste layout, com o padrão se o estilo veio sem ela. */
export function watermarkFor(style: ClipStyle, layout: string): WatermarkPlacement {
  return style.marca_dagua?.[layout as WatermarkLayout] ?? defaultWatermark(layout);
}

export function withWatermark(
  style: ClipStyle,
  layout: string,
  mudanca: Partial<WatermarkPlacement>,
): ClipStyle {
  const todos = Object.fromEntries(
    WATERMARK_LAYOUTS.map((l) => [l, watermarkFor(style, l)]),
  ) as Record<WatermarkLayout, WatermarkPlacement>;
  const atual = todos[layout as WatermarkLayout];
  if (!atual) return style;
  const novo = { ...atual, ...mudanca };
  novo.x = Math.min(1, Math.max(0, novo.x));
  novo.y = Math.min(1, Math.max(0, novo.y));
  novo.largura = Math.min(WATERMARK_MAX_WIDTH, Math.max(WATERMARK_MIN_WIDTH, novo.largura));
  novo.opacidade = Math.min(1, Math.max(WATERMARK_MIN_OPACITY, novo.opacidade));
  return { ...style, marca_dagua: { ...todos, [layout]: novo } };
}

export interface ClipStyle {
  marca: string;
  legenda: { cor: string; estilo: CaptionEstilo; tamanho: CaptionTamanho; altura: number };
  titulo: { ligado: boolean; fundo: string; texto: string };
  arroba: { texto: string; ligado: boolean };
  fonte: string;
  marca_dagua: Record<WatermarkLayout, WatermarkPlacement>;
}

export function defaultStyle(): ClipStyle {
  return {
    marca: DEFAULT_BRAND,
    legenda: { cor: DEFAULT_BRAND, estilo: "caixa", tamanho: "M", altura: CAPTION_Y_DEFAULT },
    titulo: { ligado: true, fundo: INK, texto: WHITE },
    arroba: { texto: "", ligado: true },
    fonte: DEFAULT_FONT_KEY,
    marca_dagua: Object.fromEntries(
      WATERMARK_LAYOUTS.map((l) => [l, defaultWatermark(l)]),
    ) as Record<WatermarkLayout, WatermarkPlacement>,
  };
}

/** As medidas do render, em pixels do quadro de 1080x1920. */
export const MEASURES = {
  canvasW: 1080,
  canvasH: 1920,
  previewScale: 0.375,
  titleX: 140,
  titleY: 290,
  titleMaxRight: 940,
  titleSize: 72,
  titleLineHeight: 1.32,
  titlePadX: 24,
  titlePadY: 8,
  handleSize: 32,
  handleGap: 14,
  // "Capa + banner": a capa vai até 768, o banner fica centrado nessa emenda e a faixa
  // do @ encosta embaixo dele (layout.generate_banner e generate_divider_bar).
  coverH: 768,
  bannerTitleSize: 60,
  bannerLineHeight: 1.3,
  bannerPadY: 34,
  barH: 54,
  barTextFrac: 0.4,
  barTracking: 0.18,
  barGap: 2.4,
  captionY: 1205,
  captionSizeFullscreen: 88,
  captionSizeCover: 80,
  captionOutlineFullscreen: 9,
  captionOutlineCover: 8,
  boxPaddingX: 19,
  boxRadius: 19,
  boxNeighborGap: 12,
} as const;

export const SIZE_FACTORS: Record<CaptionTamanho, number> = { P: 0.85, M: 1, G: 1.15 };

const HEX = /^#[0-9a-fA-F]{6}$/;

export function isHex(value: string): boolean {
  return HEX.test(value);
}

/** Razão de contraste do WCAG entre duas cores #RRGGBB. */
export function contrastRatio(a: string, b: string): number {
  const luminance = (color: string) => {
    const [r, g, bl] = [1, 3, 5].map((i) => {
      const c = parseInt(color.slice(i, i + 2), 16) / 255;
      return c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4;
    });
    return 0.2126 * r + 0.7152 * g + 0.0722 * bl;
  };
  const [claro, escuro] = [luminance(a), luminance(b)].sort((x, y) => y - x);
  return (claro + 0.05) / (escuro + 0.05);
}

/**
 * O que impede de salvar, em frases para quem está escolhendo.
 *
 * As mesmas regras que o servidor aplica, adiantadas: recusar só no fim faria alguém
 * montar o visual inteiro para descobrir no botão que uma cor não serve.
 */
export function styleProblems(style: ClipStyle): string[] {
  const problemas: string[] = [];
  const cores: [string, string][] = [
    ["cor da marca", style.marca],
    ["cor da legenda", style.legenda.cor],
    ["fundo do título", style.titulo.fundo],
    ["texto do título", style.titulo.texto],
  ];
  for (const [nome, cor] of cores) {
    if (!isHex(cor)) problemas.push(`A ${nome} precisa estar no formato #RRGGBB.`);
  }
  if (problemas.length) return problemas;

  const fundoLegenda = style.legenda.estilo === "caixa" ? INK : OUTLINE;
  if (contrastRatio(style.legenda.cor, fundoLegenda) < MIN_CONTRAST) {
    problemas.push("A cor da legenda fica ilegível: escolha uma cor mais clara.");
  }
  if (contrastRatio(style.titulo.texto, style.titulo.fundo) < MIN_CONTRAST) {
    problemas.push("O texto do título fica ilegível sobre esse fundo.");
  }
  if (contrastRatio(style.marca, style.titulo.fundo) < MIN_CONTRAST) {
    problemas.push("A cor da marca fica ilegível sobre o fundo do título.");
  }
  if (style.arroba.texto.length > 40) {
    problemas.push("O @ pode ter no máximo 40 caracteres.");
  }
  return problemas;
}
