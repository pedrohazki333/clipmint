"use client";

import Link from "next/link";

import { formatarCreditos, useSaldo } from "@/lib/creditos";

/**
 * O aviso de saldo baixo, com o caminho para resolver.
 *
 * Aparece onde a pessoa vai GASTAR, não numa tela de configuração: o momento
 * útil de saber que o saldo acabou é antes de montar o pedido, não depois de
 * levar 402 no botão.
 *
 * O limite do "baixo" vem do servidor (`billing_config.saldo_baixo_threshold`),
 * e não de um número escrito aqui — é decisão de negócio e muda sem deploy.
 */
export default function LowBalanceBanner() {
  const { saldo } = useSaldo();

  if (!saldo || !saldo.baixo) return null;

  const zerado = saldo.saldo <= 0;

  return (
    <div className="mb-4 flex flex-wrap items-center gap-x-3 gap-y-2 rounded-md border border-running bg-running-soft px-4 py-3">
      <p className="flex-1 text-body text-ink">
        {zerado ? (
          <>Seu saldo acabou. Sem créditos não dá para gerar clips.</>
        ) : (
          <>
            Saldo baixo:{" "}
            <span className="tabular font-medium text-running">
              {formatarCreditos(saldo.saldo)}
            </span>{" "}
            créditos — dá para menos de um vídeo médio.
          </>
        )}
      </p>
      <Link
        href="/recarga"
        className="rounded-sm bg-running px-3 py-1.5 text-label font-semibold text-base transition-opacity hover:opacity-90"
      >
        Recarregar
      </Link>
    </div>
  );
}
