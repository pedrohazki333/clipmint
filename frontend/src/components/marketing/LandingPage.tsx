import Hero from "./sections/Hero";
import Method from "./sections/Method";
import Rubric from "./sections/Rubric";
import Niches from "./sections/Niches";
import Audiences from "./sections/Audiences";
import Brand from "./sections/Brand";
import MobileSection from "./sections/MobileSection";
import Productivity from "./sections/Productivity";
import Credits from "./sections/Credits";
import Faq from "./sections/Faq";
import FinalCta from "./sections/FinalCta";
import SiteFooter from "./sections/SiteFooter";
import MobileCtaBar from "./MobileCtaBar";

/**
 * A porta de entrada para quem nunca usou o ClipMint.
 *
 * Renderizada por app/page.tsx só quando o build é público e não há sessão.
 *
 * Duas regras que esta página tem que continuar respeitando, porque quebrá-las
 * já custou uma reescrita:
 *
 *  1. **Nenhuma seção simula o produto com markup.** Todo visual passa por
 *     `Asset`, que carrega um arquivo de verdade — ver `assets.ts`. Uma tela do
 *     ClipMint desenhada em `div` fica fiel e fica morta.
 *  2. **O celular não é o desktop espremido.** Cada slot tem arte própria em
 *     pé, a barra de ação de baixo existe só lá, e o campo de link vira dois
 *     alvos cheios em vez de uma pílula apertada.
 *
 * O ritmo é o da referência que aprovamos: fundo escuro, uma ideia por tela,
 * arte grande com o texto embaixo dela, e CTA só no começo e no fim.
 */
export default function LandingPage() {
  return (
    <>
      {/*
        A revelação por scroll depende de JavaScript: o elemento nasce
        transparente e é o IntersectionObserver que o acende. Sem script não há
        observer — o `scripting: none` de globals.css cobre o navegador
        moderno, e isto cobre o resto.
      */}
      <noscript>
        <style>{`[data-reveal]{opacity:1!important;transform:none!important}`}</style>
      </noscript>

      <Hero />
      <Method />
      <Rubric />
      <Niches />
      <Audiences />
      <Brand />
      <MobileSection />
      <Productivity />
      <Credits />
      <Faq />
      <FinalCta />
      <SiteFooter />

      {/* Espaço para a barra fixa não cobrir o rodapé. */}
      <div aria-hidden className="h-24 md:hidden" />
      <MobileCtaBar />
    </>
  );
}
