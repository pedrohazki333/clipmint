/**
 * O `@/personal` do build público: vazio.
 *
 * O alias do webpack em next.config.ts aponta `@/personal` para cá quando
 * PERSONAL_BUILD não está ligado. Como as listas são vazias, a home não
 * renderiza os cards das features pessoais — e, mais importante, o módulo real
 * (com as rotas e as chamadas de API delas) nunca é resolvido, então não existe
 * nada para o bundler incluir.
 *
 * Precisa exportar exatamente os mesmos nomes que src/personal/index.ts.
 */

import type { Niche, Tool } from "@/lib/features";
import type { LayoutMode, SourceType } from "@/lib/types";

export const PERSONAL_NICHES: Niche[] = [];
/** Nenhuma rubrica pessoal — nem o nome de uma chega ao bundle público. */
export const PERSONAL_LAYOUT_RUBRICS: Partial<Record<LayoutMode, SourceType[]>> = {};
export const PERSONAL_TOOLS: Tool[] = [];

/**
 * O aprendizado não existe no build público — nem a seção da home, nem o botão
 * de salvar exemplo. `null` faz a home e o card do clipe não renderizarem nada,
 * e o módulo real nunca é resolvido.
 */
export const LearningSection: (() => null) | null = null;
export const SaveExampleButton: (() => null) | null = null;

/** A fila de postagem não existe no build público. */
export const SchedulePanel: (() => null) | null = null;
