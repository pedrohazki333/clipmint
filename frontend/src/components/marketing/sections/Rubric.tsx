import Asset from "../Asset";
import Reveal from "../Reveal";
import { RUBRICA } from "../copy";
import { Container, Eyebrow, SectionTitle } from "../ui";

/**
 * A rubrica.
 *
 * Esta seção ocupa, na página, o lugar onde a referência põe depoimento e
 * número de seguidores. Nós não temos nem um nem outro — o produto é novo — e
 * inventar seria a única coisa realmente imperdoável numa landing.
 *
 * O que temos é o critério à mostra: a nota, os cinco eixos e o motivo escrito
 * de cada corte. É prova de método em vez de prova de fama, e tem uma vantagem
 * sobre a outra: quem duvida pode conferir na primeira geração.
 *
 * Os cinco eixos são os MESMOS de `SCORE_AXES` em lib/types — se a rubrica
 * mudar lá dentro, esta lista mente.
 */
export default function Rubric() {
  return (
    <section aria-labelledby="rubrica-titulo" className="pb-24 sm:pb-32">
      <Container>
        <div className="grid items-center gap-12 lg:grid-cols-2 lg:gap-16">
          <div className="max-w-xl">
            <Eyebrow>{RUBRICA.eyebrow}</Eyebrow>
            <SectionTitle className="mt-5">
              <span id="rubrica-titulo">{RUBRICA.title}</span>
            </SectionTitle>
            <p className="mt-5 text-lead text-ink-dim">{RUBRICA.sub}</p>

            <ul className="mt-8 flex flex-col divide-y divide-line border-y border-line">
              {RUBRICA.eixos.map((eixo) => (
                <li
                  key={eixo.nome}
                  className="flex items-baseline justify-between gap-4 py-3"
                >
                  <span className="text-body font-medium text-ink">
                    {eixo.nome}
                  </span>
                  <span className="text-right text-body text-ink-dim">
                    {eixo.hint}
                  </span>
                </li>
              ))}
            </ul>
          </div>

          <Reveal variant="up">
            <Asset
              slot="rubrica"
              className="rounded-md border border-line bg-gradient-to-b from-inset to-raised"
            />
          </Reveal>
        </div>
      </Container>
    </section>
  );
}
