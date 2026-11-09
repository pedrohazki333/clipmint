import type { ClipStyle } from "@/lib/clipStyle";
import type { LayoutMode, SubtitleMode } from "@/lib/types";

/**
 * As quatro legendas que a tela oferece, e o que cada uma vira no pedido.
 *
 * O servidor fala em dois campos: o modo (`subtitle_mode`) e, quando a palavra
 * falada se destaca, como ela se destaca (`caption_style`). A tela junta os dois
 * numa escolha só, porque para quem escolhe são quatro visuais, e não uma matriz.
 */
export type CaptionChoice = "dinamica" | "caixa" | "classica" | "nenhuma";

export const CAPTION_CHOICES: {
  value: CaptionChoice;
  nome: string;
  descricao: string;
  mode: SubtitleMode;
  estilo?: "cor" | "caixa";
}[] = [
  {
    value: "dinamica",
    nome: "Dinâmica",
    descricao: "A palavra falada muda de cor, uma de cada vez",
    mode: "word_highlight",
    estilo: "cor",
  },
  {
    value: "caixa",
    nome: "Caixa",
    descricao: "A palavra falada ganha uma caixa na cor da legenda",
    mode: "word_highlight",
    estilo: "caixa",
  },
  {
    value: "classica",
    nome: "Clássica",
    descricao: "Blocos de texto, sem destaque",
    mode: "traditional",
  },
  {
    value: "nenhuma",
    nome: "Sem legenda",
    descricao: "Só o vídeo, sem texto queimado",
    mode: "none",
  },
];

export function captionChoiceFor(mode: SubtitleMode, style: ClipStyle): CaptionChoice {
  if (mode === "none") return "nenhuma";
  if (mode === "traditional") return "classica";
  return style.legenda.estilo === "cor" ? "dinamica" : "caixa";
}

export function captionChoice(value: CaptionChoice) {
  return CAPTION_CHOICES.find((c) => c.value === value) ?? CAPTION_CHOICES[1];
}

/** O estilo com o destaque que a pessoa escolheu — o que a prévia deve mostrar. */
export function styleWithChoice(base: ClipStyle, value: CaptionChoice): ClipStyle {
  const escolha = captionChoice(value);
  if (!escolha.estilo || escolha.estilo === base.legenda.estilo) return base;
  return { ...base, legenda: { ...base.legenda, estilo: escolha.estilo } };
}

/** Os nomes curtos dos layouts, para os cartões. O longo fica em LAYOUT_LABELS. */
export const LAYOUT_SHORT: Record<LayoutMode, string> = {
  fullscreen: "Tela cheia",
  cover: "Capa + faixa",
  streamer: "Facecam",
  crop: "Crop 9:16",
  original: "Original",
};
