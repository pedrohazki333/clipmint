import { PERSONAL_LAYOUT_RUBRICS } from "@/personal";
import type { LayoutMode, SourceType } from "./types";

/**
 * Quais layouts existem, e qual rubrica pode usar cada um.
 *
 * ESPELHO de `backend/app/layouts.py`. As duas cópias existem porque a decisão
 * é tomada nos dois lados — a tela precisa saber o que oferecer, o servidor
 * precisa recusar o que não serve. Divergirem é bug: um layout liberado só aqui
 * vira um botão que o servidor recusa; só lá, uma opção que ninguém vê.
 * `backend/tests/test_layouts.py` compara os dois.
 *
 * Dois modos presumem coisas sobre o conteúdo: a **capa** é escolhida pelo
 * quadro mais expressivo de um rosto falando, e a **facecam empilhada** precisa
 * de uma câmera separada do gameplay. Os outros dois não presumem nada.
 */

/**
 * layout → rubricas PÚBLICAS que o aceitam. Lista vazia = serve a todas.
 *
 * Só o que existe nos dois builds. As rubricas pessoais entram por
 * `PERSONAL_LAYOUT_RUBRICS`, que é vazia no stub — senão o nome de uma feature
 * que o build público não tem viajaria no bundle dele como valor desta tabela.
 */
export const BASE_LAYOUT_RUBRICS: Record<LayoutMode, SourceType[]> = {
  cover: ["podcast"],
  streamer: ["gameplay"],
  crop: [],
  original: [],
};

/** A tabela completa deste build: a pública mais o que o pessoal acrescenta. */
export const LAYOUT_RUBRICS: Record<LayoutMode, SourceType[]> = Object.fromEntries(
  (Object.keys(BASE_LAYOUT_RUBRICS) as LayoutMode[]).map((layout) => [
    layout,
    // Lista vazia é "serve a todas": acrescentar uma rubrica a ela seria
    // RESTRINGIR o layout, e não ampliá-lo.
    BASE_LAYOUT_RUBRICS[layout].length === 0
      ? []
      : [...BASE_LAYOUT_RUBRICS[layout], ...(PERSONAL_LAYOUT_RUBRICS[layout] ?? [])],
  ]),
) as Record<LayoutMode, SourceType[]>;

export const LAYOUT_LABELS: Record<LayoutMode, { nome: string; descricao: string }> = {
  cover: {
    nome: "Capa + banner",
    descricao: "Capa com o rosto, título em destaque e o vídeo embaixo",
  },
  streamer: {
    nome: "Facecam + gameplay",
    descricao: "A câmera em cima, o jogo embaixo",
  },
  crop: {
    nome: "Crop vertical",
    descricao: "Recorte 9:16 no centro, sem camadas",
  },
  original: {
    nome: "Layout original",
    descricao: "Sem reenquadrar: o corte sai como está no vídeo de origem",
  },
};

/** Os layouts que esta rubrica aceita, na ordem de exibição. */
export function layoutsFor(source: SourceType): LayoutMode[] {
  return (Object.keys(LAYOUT_RUBRICS) as LayoutMode[]).filter((layout) => {
    const rubricas = LAYOUT_RUBRICS[layout];
    return rubricas.length === 0 || rubricas.includes(source);
  });
}

export function layoutAllowed(layout: LayoutMode, source: SourceType): boolean {
  return layoutsFor(source).includes(layout);
}
