import Reveal from "../Reveal";
import { PRODUCTIVITY } from "../copy";
import { Container, SectionTitle } from "../ui";

/**
 * Produtividade.
 *
 * Respiro. Depois do clipe em destaque, a página fica só de tipografia e
 * espaço — nenhum card, nenhuma tela, nenhum gráfico. A seção não fala de
 * funcionalidade, fala de consequência, e a consequência não tem interface para
 * mostrar.
 *
 * As três ideias entram em sequência curta conforme o scroll, com atraso de
 * 90ms entre elas. É o único stagger da página, e existe porque a ordem delas é
 * uma frase: mais clips, menos trabalho, mais oportunidades.
 */
export default function Productivity() {
  return (
    <section aria-labelledby="produtividade-titulo" className="pb-32 sm:pb-44">
      <Container>
        <div className="max-w-3xl">
          <SectionTitle>
            <span id="produtividade-titulo">{PRODUCTIVITY.title}</span>
          </SectionTitle>
          <p className="mt-6 max-w-2xl text-lead text-ink-dim">
            {PRODUCTIVITY.texto}
          </p>
        </div>

        <div className="mt-20 grid gap-12 border-t border-line pt-12 sm:mt-24 sm:grid-cols-3 sm:gap-8">
          {PRODUCTIVITY.ideias.map((ideia, i) => (
            <Reveal key={ideia.forte} variant="up" delay={i * 90}>
              <p className="text-section font-semibold text-ink">{ideia.forte}</p>
              <p className="mt-1 text-lead text-ink-dim">{ideia.fraco}</p>
            </Reveal>
          ))}
        </div>
      </Container>
    </section>
  );
}
