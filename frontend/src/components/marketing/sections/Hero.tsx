import { HERO } from "../copy";
import Asset from "../Asset";
import HeroUrlForm from "../HeroUrlForm";
import { Container, Eyebrow } from "../ui";

/**
 * A primeira tela.
 *
 * Centralizada, e não em duas colunas: com a arte embaixo em vez de ao lado,
 * ela ganha a largura inteira e o celular recebe a MESMA composição do desktop,
 * só que mais estreita — nada é reorganizado às pressas na quebra.
 *
 * O campo de link vem antes da arte de propósito: é a única ação da primeira
 * tela, e enterrá-la abaixo de uma imagem grande custaria justamente as pessoas
 * que já chegaram decididas.
 */
export default function Hero() {
  return (
    <section className="pb-16 pt-10 sm:pt-16 lg:pb-24">
      <Container>
        <div className="mx-auto flex max-w-3xl flex-col items-center text-center">
          <Eyebrow>{HERO.eyebrow}</Eyebrow>
          <h1 className="mt-5 text-hero font-semibold text-ink">
            {HERO.headline}
          </h1>
          <p className="mt-5 max-w-2xl text-lead text-ink-dim">{HERO.sub}</p>

          <div className="mt-9 w-full max-w-xl">
            <HeroUrlForm />
          </div>
          <p className="mt-3 text-body text-ink-dim">{HERO.microcopy}</p>
        </div>

        {/* Marca o fim do CTA do hero: a barra fixa do celular só acende
            quando esta linha passa para cima da tela. Ver MobileCtaBar. */}
        <div aria-hidden data-cta-sentinela className="h-px w-full" />

        <Asset
          slot="hero"
          priority
          className="mx-auto mt-12 w-full max-w-4xl sm:mt-16"
        />

        {/* As duas rubricas, como a referência faz com os modelos dela: uma
            fileira curta de pílulas que diz de cara para quem o produto é. */}
        <ul className="mt-8 flex flex-wrap justify-center gap-2">
          {HERO.nichos.map((nicho) => (
            <li
              key={nicho}
              className="rounded-full border border-line bg-raised px-4 py-2 text-body text-ink-dim"
            >
              {nicho}
            </li>
          ))}
        </ul>
      </Container>
    </section>
  );
}
