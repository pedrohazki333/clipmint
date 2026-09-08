import Reveal from "../Reveal";
import { AUDIENCES } from "../copy";
import { Container, SectionTitle } from "../ui";

/**
 * Dois públicos.
 *
 * Aqui a interface sai de cena. A seção anterior era o produto; esta é sobre
 * quem vai usá-lo, e a pergunta que o visitante está fazendo mudou de "o que
 * isso faz?" para "isso serve pra mim?". Nenhum screenshot, nenhum card:
 * espaço, tipografia e um fio separando as duas respostas.
 *
 * A revelação é `fade`, sem deslocamento — o contrário da continuidade física
 * do hero. A mudança de contexto tem que ser sentida, e o jeito de senti-la é o
 * movimento parar.
 */
export default function Audiences() {
  return (
    <section aria-labelledby="publicos-titulo" className="py-28 sm:py-36">
      <Container>
        <Reveal variant="fade">
          <SectionTitle className="max-w-4xl">
            <span id="publicos-titulo">{AUDIENCES.title}</span>
          </SectionTitle>
        </Reveal>

        <div className="mt-16 grid border-t border-line md:grid-cols-2 sm:mt-20">
          {AUDIENCES.blocos.map((bloco, i) => (
            <Reveal
              key={bloco.pergunta}
              variant="fade"
              delay={i * 120}
              className={
                i === 0
                  ? "pt-12 md:pr-14"
                  : "border-t border-line pt-12 md:border-l md:border-t-0 md:pl-14"
              }
            >
              <p className="text-lead text-ink-dim">{bloco.pergunta}</p>
              <p className="mt-3 max-w-md text-section font-semibold text-ink">
                {bloco.resposta}
              </p>
            </Reveal>
          ))}
        </div>
      </Container>
    </section>
  );
}
