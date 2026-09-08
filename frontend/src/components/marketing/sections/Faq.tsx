"use client";

import { useId, useState } from "react";

import { FAQ } from "../copy";
import { Container, SectionTitle } from "../ui";

/**
 * FAQ.
 *
 * Um accordion de verdade: botão real, `aria-expanded`, `aria-controls`, e a
 * resposta continua no DOM (colapsada por altura) para o leitor de tela
 * encontrar a relação. Nada de `hover` — no celular hover não existe, e esta é
 * a seção em que a pessoa está tirando a última dúvida antes de decidir.
 *
 * A expansão anima `grid-template-rows` de 0fr para 1fr em vez de `height`:
 * é o único jeito de animar até a altura natural do conteúdo sem medir nada em
 * JavaScript e sem number mágico que quebra quando a resposta cresce.
 *
 * Os itens não entram por scroll. Cinco perguntas aparecendo uma a uma seria
 * animação sem função, e o conteúdo aqui é informação, não impressão.
 */
export default function Faq() {
  const [aberta, setAberta] = useState<number | null>(null);
  const base = useId();

  return (
    <section aria-labelledby="faq-titulo" className="pb-32 sm:pb-44">
      <Container>
        <SectionTitle>
          <span id="faq-titulo">{FAQ.title}</span>
        </SectionTitle>

        <ul className="mt-12 max-w-3xl border-t border-line">
          {FAQ.itens.map((item, i) => {
            const abertaAqui = aberta === i;
            const idResposta = `${base}-resposta-${i}`;
            return (
              <li key={item.pergunta} className="border-b border-line">
                <h3>
                  <button
                    type="button"
                    aria-expanded={abertaAqui}
                    aria-controls={idResposta}
                    onClick={() => setAberta(abertaAqui ? null : i)}
                    // py-5 no celular é o que garante o alvo de toque: a
                    // pergunta inteira é clicável, não só o texto dela.
                    className="flex w-full items-start justify-between gap-6 py-5 text-left"
                  >
                    <span className="text-lead font-medium text-ink">
                      {item.pergunta}
                    </span>
                    <span
                      aria-hidden
                      className={`mt-1 flex-shrink-0 text-ink-dim transition-transform duration-200 ${
                        abertaAqui ? "rotate-45" : ""
                      }`}
                    >
                      <svg
                        viewBox="0 0 24 24"
                        className="h-4 w-4"
                        fill="none"
                        stroke="currentColor"
                        strokeWidth="1.75"
                        strokeLinecap="round"
                      >
                        <path d="M12 5v14M5 12h14" />
                      </svg>
                    </span>
                  </button>
                </h3>
                <div
                  id={idResposta}
                  // Colapsado por altura, o texto continuaria no fluxo do leitor
                  // de tela e da navegação por Tab. `inert` tira do caminho o
                  // que está fechado, sem tirar do DOM o que precisa animar.
                  inert={!abertaAqui}
                  className={`grid transition-[grid-template-rows] duration-200 ease-out ${
                    abertaAqui ? "grid-rows-[1fr]" : "grid-rows-[0fr]"
                  }`}
                >
                  <div className="overflow-hidden">
                    <p className="max-w-2xl pb-6 pr-10 text-body text-ink-dim">
                      {item.resposta}
                    </p>
                  </div>
                </div>
              </li>
            );
          })}
        </ul>
      </Container>
    </section>
  );
}
