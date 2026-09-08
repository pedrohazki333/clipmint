import Asset from "../Asset";
import Reveal from "../Reveal";
import { NICHES } from "../copy";
import { Container, SectionTitle } from "../ui";

/**
 * Os dois nichos.
 *
 * A versão anterior desenhava aqui uma onda de áudio em `span` e uma tela de
 * jogo em gradiente. Era engenhoso e era falso: ninguém olha um retângulo
 * hachurado e sente "gameplay". Agora são duas artes, e o código só as coloca
 * lado a lado.
 */
const BLOCOS = [
  { slot: "podcast", ...NICHES.podcast },
  { slot: "gameplay", ...NICHES.gameplay },
] as const;

export default function Niches() {
  return (
    <section aria-labelledby="nichos-titulo" className="pb-24 sm:pb-32">
      <Container>
        <SectionTitle className="mx-auto max-w-2xl text-center">
          <span id="nichos-titulo">{NICHES.title}</span>
        </SectionTitle>

        <div className="mt-14 grid gap-5 md:grid-cols-2 sm:mt-16">
          {BLOCOS.map((bloco, i) => (
            <Reveal key={bloco.nome} variant={i === 0 ? "left" : "right"}>
              <div className="flex h-full flex-col overflow-hidden rounded-md border border-line bg-gradient-to-b from-inset to-raised">
                <Asset slot={bloco.slot} className="w-full" />
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
