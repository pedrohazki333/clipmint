import Link from "next/link";

import { AvatarIcon } from "@/lib/avatars";
import { PUBLIC_NICHES } from "@/lib/features";
import { HOW_IT_WORKS_STEPS } from "@/lib/how-it-works";

/**
 * A porta de entrada para quem nunca usou o ClipMint.
 *
 * Renderizada por app/page.tsx só quando o build é público e não há sessão —
 * quem já está logado nunca vê isto, cai direto em PerfisDashboard. Reaproveita
 * os mesmos tokens visuais e o mesmo estilo de card do resto do app: nada de
 * paleta ou tipografia nova só porque é a "primeira impressão".
 */
export default function LandingPage() {
  return (
    <div className="flex flex-col gap-16 pb-8">
      <section className="flex flex-col items-start gap-4 pt-4 sm:pt-8">
        <p className="text-label font-medium uppercase tracking-wide text-mint">
          A partir de vídeos longos do YouTube
        </p>
        <h1 className="text-display font-semibold text-ink sm:text-3xl">
          Clipes verticais que prendem atenção, sem editar nada na mão.
        </h1>
        <p className="max-w-xl text-body text-ink-dim">
          Cole o link de um vídeo, escolha o perfil e o ClipMint encontra os
          melhores trechos, corta em formato vertical e entrega pronto pra
          postar — com legenda e marca aplicadas.
        </p>
        <div className="flex flex-wrap gap-3 pt-2">
          <Link
            href="/login"
            className="rounded-sm bg-mint-strong px-5 py-2.5 text-body font-medium text-base transition-colors hover:bg-mint"
          >
            Criar conta grátis
          </Link>
          <Link
            href="#como-funciona"
            className="rounded-sm border border-line px-5 py-2.5 text-body font-medium text-ink transition-colors hover:border-line-strong"
          >
            Ver como funciona
          </Link>
        </div>
      </section>

      <section id="como-funciona" className="flex flex-col gap-6 scroll-mt-6">
        <div>
          <h2 className="text-title font-semibold text-ink">Como funciona</h2>
          <p className="mt-1 text-body text-ink-dim">
            Quatro passos, do link ao clipe pronto.
          </p>
        </div>
        <div className="grid gap-3 sm:grid-cols-2 sm:gap-4 lg:grid-cols-4">
          {HOW_IT_WORKS_STEPS.map((step, i) => (
            <div
              key={step.title}
              className="flex flex-col rounded-md border border-line bg-raised p-5"
            >
              <div className="mb-3 flex h-11 w-11 items-center justify-center rounded-sm border border-line bg-inset text-mint">
                <AvatarIcon name={step.icon} className="h-5 w-5" />
              </div>
              <p className="text-label text-ink-muted">Passo {i + 1}</p>
              <h3 className="text-body font-semibold text-ink">{step.title}</h3>
              <p className="mt-1 text-body text-ink-dim">{step.blurb}</p>
            </div>
          ))}
        </div>
        <Link
          href="/como-funciona"
          className="text-body font-medium text-mint transition-colors hover:text-mint-strong"
        >
          Ver o passo a passo completo →
        </Link>
      </section>

      <section className="flex flex-col gap-6">
        <div>
          <h2 className="text-title font-semibold text-ink">Feito para o seu nicho</h2>
          <p className="mt-1 text-body text-ink-dim">
            Cada nicho avalia os trechos do jeito certo pra ele.
          </p>
        </div>
        <div className="grid gap-3 sm:grid-cols-2 sm:gap-4">
          {PUBLIC_NICHES.map((nicho) => (
            <div
              key={nicho.source}
              className={`flex flex-col rounded-md border border-line bg-raised p-5 transition-colors ${nicho.accent}`}
            >
              <h3 className="text-title font-semibold text-ink">{nicho.title}</h3>
              <p className="mt-1 text-body text-ink-dim">{nicho.description}</p>
            </div>
          ))}
        </div>
      </section>

      <section className="rounded-md border border-line bg-raised p-6 sm:p-8">
        <h2 className="text-title font-semibold text-ink">Pague só pelo que gerar</h2>
        <p className="mt-2 max-w-xl text-body text-ink-dim">
          1 crédito equivale a 1 minuto de vídeo de origem processado. Sem
          mensalidade obrigatória — a cobrança acontece só quando um vídeo é
          processado.
        </p>
        <Link
          href="/login"
          className="mt-5 inline-block rounded-sm bg-mint-strong px-5 py-2.5 text-body font-medium text-base transition-colors hover:bg-mint"
        >
          Criar conta grátis
        </Link>
      </section>

      <footer className="border-t border-line pt-6 text-label text-ink-muted">
        <p>
          ClipMint — cortes verticais a partir de vídeos longos.{" "}
          <Link href="/como-funciona" className="text-ink-dim hover:text-ink">
            Como usar
          </Link>
        </p>
      </footer>
    </div>
  );
}
