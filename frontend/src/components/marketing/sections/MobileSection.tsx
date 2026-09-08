import Asset from "../Asset";
import Reveal from "../Reveal";
import { MOBILE } from "../copy";
import { Container, SectionTitle } from "../ui";

/**
 * No celular.
 *
 * Antes esta seção montava dois aparelhos com `div` e desenhava dentro deles
 * uma versão em miniatura das telas do app, com texto de 8px. Era ilegível
 * exatamente no aparelho que ela dizia atender. Agora é uma arte só.
 */
export default function MobileSection() {
  return (
    <section aria-labelledby="mobile-titulo" className="pb-24 sm:pb-32">
      <Container>
        <div className="grid items-center gap-12 lg:grid-cols-2 lg:gap-16">
          <Reveal variant="up" className="lg:order-2">
            <Asset slot="celular" className="mx-auto max-w-md lg:max-w-none" />
          </Reveal>

          <div className="max-w-xl lg:order-1">
            <SectionTitle>
              <span id="mobile-titulo">{MOBILE.title}</span>
            </SectionTitle>
            <p className="mt-5 text-lead text-ink-dim">{MOBILE.texto}</p>
          </div>
        </div>
      </Container>
    </section>
  );
}
