import { FINAL_CTA } from "../copy";
import HeroUrlForm from "../HeroUrlForm";
import { Container, Eyebrow } from "../ui";

/**
 * O fim.
 *
 * O mesmo campo do hero, de novo. Quem rolou a página inteira não deveria ter
 * que voltar ao topo para começar — e repetir a AÇÃO não é repetir o argumento:
 * a seção continua sem print, sem lista de benefícios e sem nada novo para ler.
 */
export default function FinalCta() {
  return (
    <section aria-labelledby="cta-titulo" className="pb-28 pt-8 sm:pb-40">
      <Container>
        <div className="mx-auto flex max-w-3xl flex-col items-center text-center">
          <Eyebrow>{FINAL_CTA.eyebrow}</Eyebrow>
          <h2 id="cta-titulo" className="mt-6 text-hero font-semibold text-ink">
            {FINAL_CTA.headline}
          </h2>
          <p className="mt-6 max-w-xl text-lead text-ink-dim">
            {FINAL_CTA.texto}
          </p>

          <div className="mt-10 w-full max-w-xl">
            <HeroUrlForm />
          </div>
          <p className="mt-3 text-body text-ink-dim">{FINAL_CTA.microcopy}</p>
        </div>
      </Container>
    </section>
  );
}
