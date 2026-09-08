import Asset from "../Asset";
import Reveal from "../Reveal";
import { SETUP } from "../copy";
import { Container, SectionTitle } from "../ui";

/**
 * A marca do perfil.
 *
 * Substitui o diagrama conceitual que havia aqui (nós, fios e retângulos em
 * CSS). O diagrama explicava a ideia; a arte mostra o resultado dela, que é o
 * mesmo clipe saindo com três marcas diferentes — e isso dispensa a explicação.
 *
 * A landing continua sem prometer os campos do formulário de perfil: a
 * arquitetura prevê simplificá-los, e congelar aqui a tela de hoje seria vender
 * uma coisa que vai mudar.
 */
export default function Brand() {
  return (
    <section aria-labelledby="marca-titulo" className="pb-24 sm:pb-32">
      <Container>
        <div className="mx-auto max-w-2xl text-center">
          <SectionTitle>
            <span id="marca-titulo">{SETUP.title}</span>
          </SectionTitle>
          <p className="mt-5 text-lead text-ink-dim">{SETUP.sub}</p>
        </div>

        <Reveal variant="up" className="mt-14 sm:mt-16">
          <Asset
            slot="marca"
            className="mx-auto max-w-5xl rounded-md border border-line bg-gradient-to-b from-inset to-raised"
          />
        </Reveal>
      </Container>
    </section>
  );
}
