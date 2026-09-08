import Asset from "../Asset";
import Reveal from "../Reveal";
import { METODO } from "../copy";
import { Container, Eyebrow, SectionTitle } from "../ui";

/**
 * Como funciona — dois blocos, duas artes.
 *
 * O padrão é o da referência e funciona por um motivo: a arte grande em cima,
 * o nome e a explicação embaixo dela. O visual carrega o argumento; o texto só
 * confirma o que a pessoa já entendeu olhando.
 *
 * Os dois cards têm um leve gradiente próprio para a arte não flutuar no preto
 * — é o que dá a eles o peso de "peça", e não de "imagem colada na página".
 */
const SLOTS = ["momento", "vertical"] as const;

export default function Method() {
  return (
    <section aria-labelledby="metodo-titulo" className="pb-24 sm:pb-32">
      <Container>
        <div className="mx-auto flex max-w-2xl flex-col items-center text-center">
          <Eyebrow>{METODO.eyebrow}</Eyebrow>
          <SectionTitle className="mt-5">
            <span id="metodo-titulo">{METODO.title}</span>
          </SectionTitle>
          <p className="mt-5 text-lead text-ink-dim">{METODO.sub}</p>
        </div>

        <div className="mt-14 grid gap-5 md:grid-cols-2 sm:mt-16">
          {METODO.blocos.map((bloco, i) => (
            <Reveal key={bloco.nome} variant="up" delay={i * 90}>
              <div className="flex h-full flex-col overflow-hidden rounded-md border border-line bg-gradient-to-b from-inset to-raised">
                <Asset slot={SLOTS[i]} className="w-full" />
                <div className="p-6 sm:p-7">
                  <h3 className="text-title font-semibold text-ink">
                    {bloco.nome}
                  </h3>
                  <p className="mt-2 text-body leading-relaxed text-ink-dim">
                    {bloco.texto}
                  </p>
                </div>
              </div>
            </Reveal>
          ))}
        </div>
      </Container>
    </section>
  );
}
