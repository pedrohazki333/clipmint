/**
 * As listas do que a versão pessoal acrescenta — sem importar componente.
 *
 * Ficam separadas de `index.ts` para quebrar um ciclo real: o index exporta
 * `LearningSection`, que importa `ReferenceForm`, que precisa desta lista. Se
 * ela morasse no index, o `ReferenceForm` leria `PERSONAL_NICHES` enquanto o
 * index ainda estava inicializando — `undefined`, e o spread estourava na
 * primeira renderização da home.
 *
 * Quem é público importa de `@/personal` (o index, que o build público troca
 * pelo stub). Quem já é pessoal pode importar daqui direto, porque no público
 * esses arquivos nem entram no grafo.
 */

import type { Niche, Tool, ToolCount } from "@/lib/features";
import type { LayoutMode, SourceType } from "@/lib/types";

import { listVideoEnhance } from "./api";

export const PERSONAL_NICHES: Niche[] = [
  {
    source: "siege",
    href: "/siege",
    title: "Siege X",
    blurb: "Sequência de abates, clutch, reflexo e treta na call",
    pageBlurb:
      "Análise por sequência de eliminações, abate rápido de um tiro, clutch e treta na call. Os presets abaixo valem só para esta conta.",
    description:
      "Avalia sequência de eliminações, abate rápido de um tiro, clutch e treta na call",
    accent: "hover:border-orange-500",
    layout: "streamer",
  },
];

export const PERSONAL_TOOLS: Tool[] = [
  {
    key: "video-enhance",
    href: "/melhorar-video",
    title: "Melhorar vídeo",
    blurb: "Vídeo do Gemini sai em 1080p com bitrate limpo",
    accent: "hover:border-fuchsia-500",
    // Melhorar vídeo não é uma conta: não tem source_type nem fila de postagem,
    // então a contagem vem da própria API, e não da lista de jobs da home.
    loadCount: async (): Promise<ToolCount> => {
      const jobs = await listVideoEnhance();
      const running = jobs.filter(
        (j) => j.status !== "done" && j.status !== "failed",
      ).length;
      return { total: jobs.length, running };
    },
  },
];

/**
 * Quais layouts as rubricas PESSOAIS aceitam.
 *
 * Mora aqui, e não em `@/lib/layouts`, porque aquele arquivo entra no bundle
 * público: a tabela lá citava "siege" como valor, e o nome da feature chegava
 * a quem não tem a feature. `layouts.ts` funde esta lista à dele — vazia no
 * stub, e aí a rubrica simplesmente não existe.
 */
export const PERSONAL_LAYOUT_RUBRICS: Partial<Record<LayoutMode, SourceType[]>> = {
  streamer: ["siege"],
};
