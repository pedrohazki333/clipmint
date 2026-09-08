import Reveal from "../Reveal";
import { CREDITS } from "../copy";
import { Container, SectionTitle } from "../ui";

/**
 * Créditos.
 *
 * Depois dos aparelhos, a densidade cai: aqui só existe informação prática, e
 * ela precisa caber numa frase. Uma tabela de planos nesta altura da página
 * trocaria "é fácil começar" por "escolha entre quatro opções" — a comparação
 * de pacotes vive na tela de recarga, dentro do produto, para quem já entendeu
 * a regra.
 *
 * O 120 é grande e está parado. Contador animando de 0 a 120 seria efeito de
 * apresentação: chamaria atenção para a animação, não para o número.
 */
export default function Credits() {
  return (
    <section aria-labelledby="creditos-titulo" className="pb-32 sm:pb-44">
      <Container>
        <SectionTitle className="max-w-2xl">
          <span id="creditos-titulo">{CREDITS.title}</span>
        </SectionTitle>

        <Reveal variant="fade" className="mt-14 border-t border-line pt-12 sm:mt-16">
          <div className="grid gap-12 lg:grid-cols-[minmax(0,1fr)_auto] lg:items-end lg:gap-16">
            <p className="max-w-md text-section font-semibold text-ink">
              {CREDITS.regra}
            </p>

            <p className="flex items-baseline gap-4 lg:justify-end">
              <span className="tabular text-mega font-semibold text-mint">
                {CREDITS.numero}
              </span>
              <span className="font-mono text-label uppercase leading-snug tracking-[0.18em] text-ink-dim">
                {CREDITS.rotulo}
                <br />
                {CREDITS.complemento}
              </span>
            </p>
          </div>
        </Reveal>
      </Container>
    </section>
  );
}
