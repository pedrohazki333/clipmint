/**
 * O estilo do clipe, do lado da tela.
 *
 * ESPELHO de `backend/app/clip_style.py` e das medidas de `services/title_card.py` e
 * `services/subtitler.py`. As duas cópias existem porque a prévia precisa responder na
 * hora, a cada cor escolhida, e o servidor é quem decide de verdade. Divergirem é bug:
 * a prévia mentiria sobre o clipe. `backend/tests/test_clip_style_parity.py` compara.
 */

export const DEFAULT_BRAND = "#FD375C";
export const INK = "#0B0B0C";
export const OUTLINE = "#000000";
export const WHITE = "#FFFFFF";
export const MIN_CONTRAST = 4.5;
export const BAND_HANDLE_COLOR = "#C9C9CF";

export const PALETTE: Record<string, string> = {
  rosa: "#FD375C",
  amarelo: "#FFD23F",
  ciano: "#3EC8FF",
  verde: "#9DFF4F",
};

export const DEFAULT_FONT_KEY = "archivo";

export type CaptionEstilo = "caixa" | "cor";
export type CaptionTamanho = "P" | "M" | "G";

export interface ClipStyle {
  marca: string;
  legenda: { cor: string; estilo: CaptionEstilo; tamanho: CaptionTamanho };
  titulo: { ligado: boolean; fundo: string; texto: string };
  arroba: { texto: string; ligado: boolean };
  fonte: string;
}

export function defaultStyle(): ClipStyle {
  return {
    marca: DEFAULT_BRAND,
    legenda: { cor: DEFAULT_BRAND, estilo: "caixa", tamanho: "M" },
    titulo: { ligado: true, fundo: INK, texto: WHITE },
    arroba: { texto: "", ligado: true },
    fonte: DEFAULT_FONT_KEY,
  };
}

/** As medidas do render, em pixels do quadro de 1080x1920. */
export const MEASURES = {
  canvasW: 1080,
  canvasH: 1920,
  previewScale: 0.375,
  titleX: 53,
  titleY: 197,
  titleMaxRight: 909,
  titleSize: 72,
  titleLineHeight: 1.32,
  titlePadX: 24,
  titlePadY: 8,
  handleSize: 32,
  handleGap: 14,
  bandY: 800,
  bandH: 256,
  bandBorder: 8,
  bandTitleSize: 67,
  bandLineHeight: 1.12,
  bandHandleSize: 29,
  bandHandleGap: 12,
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

/** O @ da faixa fica no cinza da especificação, salvo onde ele não se lê. */
export function bandHandleColor(style: ClipStyle): string {
  return contrastRatio(BAND_HANDLE_COLOR, style.titulo.fundo) >= MIN_CONTRAST
    ? BAND_HANDLE_COLOR
    : style.titulo.texto;
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
