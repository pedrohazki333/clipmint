import type { LayoutMode, SourceType } from "./types";

/**
 * O que este build oferece.
 *
 * Duas features seguem só na versão pessoal — o nicho Siege X e a aba Melhorar
 * vídeo — e não podem aparecer no produto público. A separação tem duas
 * camadas, e nenhuma delas é um `if` no meio da tela:
 *
 *  1. **Rotas**: os arquivos delas se chamam `page.personal.tsx`. O Next só
 *     reconhece esse nome como rota quando `pageExtensions` inclui
 *     "personal.tsx" — o que só acontece com PERSONAL_BUILD=1. No build público
 *     o arquivo não vira rota nem é compilado.
 *  2. **Código compartilhado**: o que a home precisa saber sobre elas mora em
 *     `@/personal`, que no build público é trocado por um stub vazio via alias
 *     do webpack. O módulo real não entra no grafo — não sobra nem como código
 *     morto no bundle.
 *
 * Este arquivo só descreve as formas e a parte pública. Nada de Siege X ou de
 * Melhorar vídeo pode ser escrito aqui.
 */

/**
 * Uma conta: tem presets de marca, fila de postagem e rubrica própria.
 *
 * Tudo que a interface diz sobre um nicho está aqui. Antes a mesma conta era
 * descrita em três lugares (home, seletor de tipo e cabeçalho da página), e
 * esconder Siege X do público exigia lembrar dos três — o terceiro passou
 * batido e vazou para o bundle na primeira tentativa.
 */
export interface Niche {
  source: SourceType;
  href: string;
  title: string;
  /** Chamada curta no card da home. */
  blurb: string;
  /** Cabeçalho da página da conta — mais longo que o `blurb` do card. */
  pageBlurb: string;
  /** O que a rubrica avalia — vira o title do seletor de tipo de conteúdo. */
  description: string;
  /** Classe Tailwind de hover do card, para as contas não se confundirem. */
  accent: string;
  /** Layout que a conta sugere ao criar um job. */
  layout: LayoutMode;
}

/** Contagem que o card da home mostra. */
export interface ToolCount {
  total: number;
  running: number;
}

/**
 * Um item da home que NÃO é uma conta: sem source_type, sem fila de postagem.
 * A contagem vem da própria feature, porque o hub não conhece a API dela.
 */
export interface Tool {
  key: string;
  href: string;
  title: string;
  blurb: string;
  accent: string;
  loadCount: () => Promise<ToolCount>;
}

export const PUBLIC_NICHES: Niche[] = [
  {
    source: "podcast",
    href: "/podcast",
    title: "Podcast",
    blurb: "Gancho verbal, arco de resolução, frase-momento",
    pageBlurb:
      "Análise por gancho verbal, arco de resolução e frase-momento. Os presets abaixo valem só para esta conta.",
    description:
      "Avalia gancho verbal, arco de resolução, frase-momento e potencial de debate",
    accent: "hover:border-mint",
    layout: "cover",
  },
  {
    source: "gameplay",
    href: "/gameplay",
    title: "Gameplay",
    blurb: "Pico visual, reviravolta, legibilidade sem som",
    pageBlurb:
      "Análise por pico visual, reviravolta e legibilidade sem som. Os presets abaixo valem só para esta conta.",
    description:
      "Avalia pico visual, reviravolta, legibilidade sem som e reação do jogador",
    accent: "hover:border-sky-500",
    layout: "streamer",
  },
];

/** Todos os nichos deste build, na ordem de exibição. */
export function allNiches(personal: Niche[]): Niche[] {
  return [...PUBLIC_NICHES, ...personal];
}
