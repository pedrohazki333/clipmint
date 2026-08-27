"use client";

import Link from "next/link";

import { formatarCreditos } from "@/lib/creditos";
import type { Estimate } from "@/lib/types";

/**
 * O aviso antes de gastar: quanto este vídeo custa e com quanto você fica.
 *
 * Existe porque o custo depende do VÍDEO, não do plano: dois cliques iguais em
 * vídeos diferentes gastam valores diferentes, e um produto que debita sem
 * dizer quanto vai debitar antes é um produto em que a pessoa para de clicar.
 *
 * Quando não dá, o botão de confirmar não vira um botão desabilitado sem saída
 * — vira o caminho para a recarga, que é o que a pessoa precisa fazer.
 */
export default function CreditConfirm({
  estimativa,
  carregando,
  erro,
  enviando,
  onConfirm,
  onCancel,
}: {
  estimativa: Estimate | null;
  carregando: boolean;
  erro: string;
  enviando: boolean;
  onConfirm: () => void;
  onCancel: () => void;
}) {
  const dá = estimativa?.suficiente ?? false;
  const sobra = estimativa ? estimativa.saldo - estimativa.creditos : 0;

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-label="Confirmar geração"
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 p-4"
      onClick={(e) => {
        if (e.target === e.currentTarget && !enviando) onCancel();
      }}
    >
      <div className="w-full max-w-md rounded-md border border-line bg-raised p-5">
        <h2 className="text-title font-semibold text-ink">Confirmar geração</h2>

        {carregando && (
          <p className="mt-4 text-body text-ink-dim">Medindo o vídeo…</p>
        )}

        {!carregando && erro && (
          <p className="mt-4 rounded-sm border border-danger bg-danger-soft px-3 py-2 text-body text-ink">
            {erro}
          </p>
        )}

        {!carregando && !erro && estimativa && (
          <>
            <dl className="mt-4 space-y-2 text-body">
              <div className="flex items-baseline justify-between gap-3">
                <dt className="text-ink-dim">Duração do vídeo</dt>
                <dd className="tabular text-ink">~{estimativa.minutos} min</dd>
              </div>
              <div className="flex items-baseline justify-between gap-3">
                <dt className="text-ink-dim">Custo</dt>
                <dd className="tabular font-medium text-ink">
                  {formatarCreditos(estimativa.creditos)} créditos
                </dd>
              </div>
              <div className="flex items-baseline justify-between gap-3 border-t border-line pt-2">
                <dt className="text-ink-dim">Seu saldo</dt>
                <dd className="tabular text-ink">
                  {formatarCreditos(estimativa.saldo)}
                </dd>
              </div>
              {dá && (
                <div className="flex items-baseline justify-between gap-3">
                  <dt className="text-ink-dim">Fica com</dt>
                  <dd className="tabular text-mint">
                    {formatarCreditos(sobra)}
                  </dd>
                </div>
              )}
            </dl>

            {!dá && (
              <p className="mt-4 rounded-sm border border-running bg-running-soft px-3 py-2 text-body text-ink">
                Faltam{" "}
                <span className="tabular font-medium text-running">
                  {formatarCreditos(estimativa.faltam)}
                </span>{" "}
                créditos para este vídeo.
              </p>
            )}

            {/* 1 crédito = 1 minuto aparece aqui, e não só na tela de recarga:
                é onde a conta acabou de ser feita e onde ela faz sentido. */}
            <p className="mt-3 text-label text-ink-muted">
              1 crédito = 1 minuto de vídeo de origem. O que sobrar da estimativa
              volta para o seu saldo quando o job terminar.
            </p>
          </>
        )}

        <div className="mt-5 flex items-center justify-end gap-2">
          <button
            type="button"
            onClick={onCancel}
            disabled={enviando}
            className="rounded-sm border border-line px-3 py-1.5 text-body text-ink-dim transition-colors hover:border-line-strong hover:text-ink disabled:opacity-50"
          >
            Cancelar
          </button>

          {!carregando && !erro && estimativa && !dá && (
            <Link
              href="/recarga"
              className="rounded-sm bg-running px-3 py-1.5 text-body font-semibold text-base transition-opacity hover:opacity-90"
            >
              Recarregar
            </Link>
          )}

          {!carregando && !erro && dá && (
            <button
              type="button"
              onClick={onConfirm}
              disabled={enviando}
              className="rounded-sm bg-mint px-3 py-1.5 text-body font-semibold text-base transition-opacity hover:opacity-90 disabled:opacity-50"
            >
              {enviando ? "Iniciando…" : "Gerar clips"}
            </button>
          )}
        </div>
      </div>
    </div>
  );
}
