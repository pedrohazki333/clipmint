import type { AvatarKey } from "./avatars";

/**
 * Os quatro passos do fluxo, em um lugar só.
 *
 * A landing usa `blurb` (curto, para o teaser) e /como-funciona usa `detail`
 * (mais longo). Mesma fonte, dois níveis de profundidade — como `blurb` e
 * `pageBlurb` já fazem em `features.ts` para os nichos.
 */
export interface HowItWorksStep {
  icon: AvatarKey;
  title: string;
  blurb: string;
  detail: string;
}

export const HOW_IT_WORKS_STEPS: HowItWorksStep[] = [
  {
    icon: "video",
    title: "Cole o link",
    blurb: "Um vídeo do YouTube: podcast, gameplay, o que for.",
    detail:
      "Informe a URL de um vídeo do YouTube já publicado. O ClipMint baixa e transcreve o áudio sozinho — não precisa enviar arquivo nem editar nada antes.",
  },
  {
    icon: "person",
    title: "Escolha o perfil",
    blurb: "Cada perfil guarda a rubrica, a marca e o padrão de geração.",
    detail:
      "Um perfil define o nicho (Podcast, Gameplay...), a marca aplicada aos clipes e o layout do corte. Crie quantos perfis quiser — um por canal ou por linha editorial.",
  },
  {
    icon: "target",
    title: "A rubrica avalia",
    blurb: "Cada trecho é pontuado por gancho, ritmo e potencial de viralizar.",
    detail:
      "A rubrica do nicho dá nota a cada trecho do vídeo — no Podcast, por gancho verbal, arco de resolução e frase-momento; no Gameplay, por pico visual, reviravolta e legibilidade sem som. Só os melhores trechos viram clipe.",
  },
  {
    icon: "sparkles",
    title: "Baixe os clipes",
    blurb: "Cortes verticais prontos, com legenda e marca já aplicadas.",
    detail:
      "Cada clipe sai cortado em formato vertical, já com legenda e a marca do perfil aplicadas — pronto para postar. 1 crédito equivale a 1 minuto do vídeo de origem processado.",
  },
];
