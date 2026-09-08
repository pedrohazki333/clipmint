"use client";

import Link from "next/link";
import { useEffect, useState } from "react";

import { ROTA_CADASTRO } from "@/lib/rotas";

/**
 * A barra de ação fixa — só no celular.
 *
 * No desktop o CTA da navbar fica sempre à vista porque a barra é grudada no
 * topo. No celular a navbar também é, mas o polegar não alcança o topo da tela:
 * quem lê com uma mão precisa do botão embaixo. É a peça que existe SÓ no
 * celular, e é de propósito — onde o uso é diferente, a interface é diferente.
 *
 * Ela só aparece depois que o CTA do hero sai da tela. Mostrar as duas ao mesmo
 * tempo seria pedir a mesma coisa duas vezes e comer 90px do primeiro quadro da
 * página, que é o mais caro que existe.
 *
 * A sentinela é desenhada pelo Hero (`data-cta-sentinela`). Observar um
 * elemento em vez de ouvir o scroll evita trabalho a cada quadro de rolagem.
 */
export default function MobileCtaBar() {
  const [visivel, setVisivel] = useState(false);

  useEffect(() => {
    const sentinela = document.querySelector("[data-cta-sentinela]");
    // Sem sentinela (ou sem observer), a barra fica visível: perder o CTA é
    // pior que mostrá-lo cedo demais.
    if (!sentinela || typeof IntersectionObserver === "undefined") {
      setVisivel(true);
      return;
    }
    const io = new IntersectionObserver(
      ([e]) => setVisivel(!e.isIntersecting && e.boundingClientRect.top < 0),
      { threshold: 0 },
    );
    io.observe(sentinela);
    return () => io.disconnect();
  }, []);

  return (
    <div
      // `hidden` em vez de desmontar: o leitor de tela e o Tab acompanham o
      // estado, e a transição tem o que animar.
      hidden={!visivel}
      className="fixed inset-x-0 bottom-0 z-40 border-t border-line bg-base px-4 pb-[max(0.75rem,env(safe-area-inset-bottom))] pt-3 transition-opacity duration-200 md:hidden"
    >
      <Link
        href={ROTA_CADASTRO}
        className="flex w-full items-center justify-center rounded-sm bg-mint-strong px-6 py-3.5 text-body font-semibold text-on-mint"
      >
        Começar grátis
      </Link>
      <p className="mt-1.5 text-center text-label text-ink-dim">
        120 créditos grátis. Sem cartão.
      </p>
    </div>
  );
}
