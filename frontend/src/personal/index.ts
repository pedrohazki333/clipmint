/**
 * O que a versão PESSOAL acrescenta.
 *
 * No build público este arquivo é substituído por `src/personal.stub.ts` via
 * NormalModuleReplacementPlugin (ver next.config.ts): o módulo real nem entra no
 * grafo, então nada daqui — nome, rota, chamada de API — alcança o bundle.
 *
 * Nada fora de `@/personal` pode citar Siege X, Melhorar vídeo ou o sistema de
 * aprendizado. Quem quiser saber se eles existem pergunta por estas exportações
 * — listas vazias e componentes nulos no stub.
 *
 * As listas moram em `./data` e são re-exportadas daqui. Ver o porquê lá: é o
 * que impede um ciclo entre este index e os componentes que ele exporta.
 */

export { PERSONAL_LAYOUT_RUBRICS, PERSONAL_NICHES, PERSONAL_TOOLS } from "./data";

/**
 * O bloco de aprendizado da home. `null` no build público, e aí a home
 * simplesmente não o renderiza — sem `if` de feature espalhado na tela.
 */
export { default as LearningSection } from "./LearningSection";

/** O botão "Salvar exemplo" do card do clipe. `null` no público. */
export { default as SaveExampleButton } from "./SaveExampleButton";

/**
 * A fila de postagem, na página do perfil. `null` no build público — a grade é
 * a do dono da instalação, não do usuário.
 */
export { default as SchedulePanel } from "@/components/SchedulePanel";
