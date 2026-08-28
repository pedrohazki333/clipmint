import Link from "next/link";
import { cookies } from "next/headers";

import { AvatarIcon } from "@/lib/avatars";
import { AUTH_COOKIE } from "@/lib/auth";
import { IS_PUBLIC_BUILD, SESSION_COOKIE } from "@/lib/build";
import { PUBLIC_NICHES } from "@/lib/features";
import { HOW_IT_WORKS_STEPS } from "@/lib/how-it-works";

export const metadata = { title: "Como usar — ClipMint" };

const FAQ: { pergunta: string; resposta: string }[] = [
  {
    pergunta: "Quanto tempo leva para gerar os clipes?",
    resposta:
      "Depende da duração do vídeo de origem — o pipeline baixa, transcreve, avalia cada trecho pela rubrica e corta. Vídeos mais longos levam mais tempo; a tela do perfil mostra o andamento em tempo real.",
  },
  {
    pergunta: "O que é a rubrica?",
    resposta:
      "É o critério que pontua cada trecho do vídeo antes de virar clipe — muda por nicho. Só os trechos com melhor nota são cortados, então nem todo vídeo vira a mesma quantidade de clipes.",
  },
  {
    pergunta: "Por que às vezes sai '0 clipes'?",
    resposta:
      "Acontece quando nenhum trecho passou da nota mínima da rubrica para aquele nicho — o vídeo foi processado, só não tinha um momento forte o suficiente. A tela explica o motivo específico quando isso acontece.",
  },
  {
    pergunta: "Como funcionam os créditos?",
    resposta:
      "1 crédito equivale a 1 minuto do vídeo de origem processado. O crédito é reservado quando o job começa e ajustado ao final, conforme o tempo realmente processado.",
  },
];

export default async function ComoFuncionaPage() {
  const loggedIn = (await cookies()).has(
    IS_PUBLIC_BUILD ? SESSION_COOKIE : AUTH_COOKIE,
  );

  return (
    <div className="flex flex-col gap-14 pb-8">
      <section className="flex flex-col gap-3 pt-4 sm:pt-8">
        <h1 className="text-display font-semibold text-ink">Como funciona</h1>
        <p className="max-w-xl text-body text-ink-dim">
          Do link do YouTube ao clipe vertical pronto pra postar, em quatro
          passos.
        </p>
      </section>

      <section className="flex flex-col gap-6">
        {HOW_IT_WORKS_STEPS.map((step, i) => (
          <div key={step.title} className="flex gap-4">
            <div className="flex h-11 w-11 shrink-0 items-center justify-center rounded-sm border border-line bg-inset text-mint">
              <AvatarIcon name={step.icon} className="h-5 w-5" />
            </div>
            <div>
              <p className="text-label text-ink-muted">Passo {i + 1}</p>
              <h2 className="text-title font-semibold text-ink">{step.title}</h2>
              <p className="mt-1 max-w-xl text-body text-ink-dim">{step.detail}</p>
            </div>
          </div>
        ))}
      </section>

      <section className="flex flex-col gap-6">
        <div>
          <h2 className="text-title font-semibold text-ink">Os nichos</h2>
          <p className="mt-1 text-body text-ink-dim">
            A rubrica muda de acordo com o que o vídeo é.
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
        <h2 className="text-title font-semibold text-ink">Créditos e cobrança</h2>
        <p className="mt-2 max-w-xl text-body text-ink-dim">
          1 crédito equivale a 1 minuto de vídeo de origem processado. A
          cobrança acontece só quando um vídeo é processado — sem mensalidade
          obrigatória.
        </p>
      </section>

      <section className="flex flex-col gap-4">
        <h2 className="text-title font-semibold text-ink">Perguntas frequentes</h2>
        <dl className="flex flex-col divide-y divide-line rounded-md border border-line bg-raised">
          {FAQ.map((item) => (
            <div key={item.pergunta} className="p-5">
              <dt className="text-body font-medium text-ink">{item.pergunta}</dt>
              <dd className="mt-1 text-body text-ink-dim">{item.resposta}</dd>
            </div>
          ))}
        </dl>
      </section>

      <section className="flex flex-col items-start gap-3">
        <Link
          href={loggedIn ? "/" : "/login"}
          className="rounded-sm bg-mint-strong px-5 py-2.5 text-body font-medium text-base transition-colors hover:bg-mint"
        >
          {loggedIn ? "Ir para meus perfis" : "Criar conta grátis"}
        </Link>
      </section>
    </div>
  );
}
