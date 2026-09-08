/**
 * O catálogo de artes da landing.
 *
 * Toda imagem e todo vídeo da página estão declarados aqui, e em nenhum outro
 * lugar. A regra que este arquivo existe para sustentar: **a landing não desenha
 * o produto com markup**. A versão anterior montava as telas com `div` e SVG —
 * ficava fiel e ficava morto, porque nenhuma pilha de `div` tem luz, reflexo,
 * profundidade ou um rosto real dentro. O que vende é a arte; o código só
 * reserva o lugar dela.
 *
 * Cada slot declara DUAS artes: uma deitada para o desktop e uma em pé para o
 * celular. Isso não é capricho — é a diferença entre uma página pensada para o
 * celular e uma página espremida nele. A referência que estamos seguindo erra
 * justamente aqui: no celular ela mostra as mesmas artes deitadas, e o texto
 * dentro delas fica ilegível.
 *
 * `mobile` é opcional. Sem ele o celular recebe a arte deitada — aceitável para
 * arte sem texto dentro, ruim para qualquer coisa com interface.
 *
 * Enquanto o arquivo não existe em `public/`, o slot desenha um marcador com o
 * briefing. Basta colocar o arquivo no caminho e recarregar: sem build, sem
 * mexer no código.
 */

export type Formato = "imagem" | "video";

export interface Arte {
  /** Caminho a partir de `public/`. */
  src: string;
  /** Dimensões reais do arquivo — o slot reserva a altura por elas. */
  w: number;
  h: number;
  /** Só para vídeo: o quadro que aparece antes de tocar. */
  poster?: string;
}

export interface Slot {
  id: string;
  formato: Formato;
  /** Alternativo da imagem. Descreve o que se vê, para quem não vê. */
  alt: string;
  /** O que a arte precisa mostrar. Vira o briefing e o texto do marcador. */
  briefing: string;
  desktop: Arte;
  mobile?: Arte;
}

const PASTA = "/landing";

export const SLOTS = {
  /** ── 01 · Hero ──────────────────────────────────────────────────────── */
  hero: {
    id: "hero",
    formato: "imagem",
    alt: "Um episódio de podcast aberto no player e, ao lado, três clipes verticais tirados dele, cada um com a sua legenda.",
    briefing:
      "O episódio longo à esquerda e os clipes verticais saindo dele à direita. É a promessa inteira numa imagem só: entra um vídeo, saem vários.",
    desktop: { src: `${PASTA}/hero-visual.webp`, w: 1336, h: 1002 },
    mobile: { src: `${PASTA}/hero-visual-mobile.webp`, w: 1080, h: 1350 },
  },

  /** ── 03 · Acha o momento ────────────────────────────────────────────── */
  momento: {
    id: "momento",
    formato: "video",
    alt: "A tela do ClipMint percorrendo um episódio e marcando os trechos que passaram na rubrica.",
    briefing:
      "A varredura acontecendo: a linha do tempo do episódio sendo percorrida e alguns trechos acendendo como escolhidos. Precisa dar a sensação de que alguma coisa está procurando, não de que uma tela está parada.",
    desktop: {
      src: `${PASTA}/momento.mp4`,
      w: 1600,
      h: 1200,
      poster: `${PASTA}/momento-poster.webp`,
    },
    mobile: {
      src: `${PASTA}/momento-mobile.mp4`,
      w: 1080,
      h: 1350,
      poster: `${PASTA}/momento-mobile-poster.webp`,
    },
  },

  /** ── 03 · Monta o vertical ──────────────────────────────────────────── */
  vertical: {
    id: "vertical",
    formato: "video",
    alt: "Um trecho 16:9 virando um clipe 9:16, com a legenda aparecendo palavra a palavra e o enquadramento seguindo o rosto.",
    briefing:
      "O antes e o depois, lado a lado: o quadro deitado do vídeo original virando o clipe em pé, com a legenda entrando palavra por palavra e o corte acompanhando o rosto. É o único lugar da página onde o movimento explica melhor que uma foto.",
    desktop: {
      src: `${PASTA}/vertical.mp4`,
      w: 1600,
      h: 1200,
      poster: `${PASTA}/vertical-poster.webp`,
    },
    mobile: {
      src: `${PASTA}/vertical-mobile.mp4`,
      w: 1080,
      h: 1350,
      poster: `${PASTA}/vertical-mobile-poster.webp`,
    },
  },

  /** ── 04 · A rubrica (prova de método) ───────────────────────────────── */
  rubrica: {
    id: "rubrica",
    formato: "imagem",
    alt: "O card de um clipe com a nota, os cinco eixos da rubrica, a frase de gancho e o motivo da escolha.",
    briefing:
      "O card de resultado em close: a nota grande, os cinco eixos, a frase de gancho entre aspas e o motivo escrito. Esta é a arte mais importante da página depois do hero — é ela que mostra que o ClipMint explica a escolha, coisa que nenhum concorrente mostra. Pode ser uma captura de tela real do produto, tratada.",
    desktop: { src: `${PASTA}/rubrica.webp`, w: 1400, h: 1050 },
    mobile: { src: `${PASTA}/rubrica-mobile.webp`, w: 1080, h: 1350 },
  },

  /** ── 05 · Nichos ────────────────────────────────────────────────────── */
  podcast: {
    id: "podcast",
    formato: "imagem",
    alt: "Dois convidados conversando num estúdio de podcast, com o trecho escolhido destacado.",
    briefing:
      "Uma conversa de podcast, com o momento escolhido em destaque. Clima de estúdio, luz baixa, nada de banco de imagens sorridente.",
    desktop: { src: `${PASTA}/podcast.webp`, w: 1200, h: 1200 },
  },
  gameplay: {
    id: "gameplay",
    formato: "imagem",
    alt: "Uma tela de gameplay cheia de ação com a facecam do jogador destacada no canto.",
    briefing:
      "Tela de jogo em ação, com a facecam do jogador marcada no canto — é o que o rastreador encontra e leva para a metade de cima do clipe.",
    desktop: { src: `${PASTA}/gameplay.webp`, w: 1200, h: 1200 },
  },

  /** ── 06 · Marca ─────────────────────────────────────────────────────── */
  marca: {
    id: "marca",
    formato: "imagem",
    alt: "O mesmo clipe com três marcas diferentes aplicadas: cores de banner, fonte e logo trocadas.",
    briefing:
      "O MESMO clipe repetido três vezes com marcas diferentes — cor do banner, fonte e logo trocadas. A ideia que a arte precisa passar: você configura uma vez e todo clipe sai assim.",
    desktop: { src: `${PASTA}/marca.webp`, w: 1500, h: 1000 },
    mobile: { src: `${PASTA}/marca-mobile.webp`, w: 1080, h: 1350 },
  },

  /** ── 07 · Celular ───────────────────────────────────────────────────── */
  celular: {
    id: "celular",
    formato: "imagem",
    alt: "O ClipMint aberto no navegador de um celular, mostrando a geração em andamento.",
    briefing:
      "Uma mão segurando um celular com o ClipMint aberto no navegador, na tela de acompanhamento do job. Precisa ser reconhecível como navegador de celular, não como app instalado — o produto roda na web e a seção existe para dizer isso.",
    desktop: { src: `${PASTA}/celular.webp`, w: 1400, h: 1050 },
    mobile: { src: `${PASTA}/celular-mobile.webp`, w: 1080, h: 1350 },
  },
} as const satisfies Record<string, Slot>;

export type SlotId = keyof typeof SLOTS;

/** Todos os slots, para o script que imprime o briefing. */
export const TODOS_OS_SLOTS: Slot[] = Object.values(SLOTS);
