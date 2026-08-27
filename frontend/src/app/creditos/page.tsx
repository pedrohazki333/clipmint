"use client";

import Link from "next/link";
import { useEffect, useState } from "react";

import { getApiErrorMessage, getLedger } from "@/lib/api";
import { formatarCreditos, useSaldo } from "@/lib/creditos";
import type { LedgerEntry, LedgerTipo } from "@/lib/types";

/**
 * Extrato: o que aconteceu com o saldo, linha a linha.
 *
 * Mostra o extrato CRU — reserva e devolução inclusive — e não um resumo já
 * mastigado. A tentação é esconder `hold`/`release` porque "se anulam", mas é
 * justamente vê-los que explica por que o saldo caiu 120 quando o job começou e
 * voltou a subir quando ele terminou. Escondidos, a mesma sequência parece
 * cobrança dupla.
 */

const RÓTULO: Record<LedgerTipo, string> = {
  topup: "Recarga",
  debito: "Processamento",
  estorno: "Estorno",
  bonus: "Bônus",
  ajuste: "Ajuste",
  hold: "Reserva",
  release: "Devolução da reserva",
};

/** Reserva e devolução são movimento interno; recarga e cobrança são dinheiro. */
const DISCRETO: LedgerTipo[] = ["hold", "release"];

function formatarData(iso: string): string {
  const d = new Date(iso);
  return d.toLocaleString("pt-BR", {
    day: "2-digit",
    month: "2-digit",
    year: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  });
}

export default function CreditosPage() {
  const { saldo } = useSaldo();
  const [linhas, setLinhas] = useState<LedgerEntry[]>([]);
  const [carregando, setCarregando] = useState(true);
  const [erro, setErro] = useState("");

  useEffect(() => {
    getLedger()
      .then(setLinhas)
      .catch((err) =>
        setErro(getApiErrorMessage(err, "Não foi possível carregar o extrato.")),
      )
      .finally(() => setCarregando(false));
  }, []);

  return (
    <div className="flex flex-col gap-5">
      <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
        <h1 className="text-title font-semibold text-ink">Extrato</h1>
        <span className="text-label text-ink-muted">
          1 crédito = 1 minuto de vídeo de origem
        </span>
        <Link
          href="/recarga"
          className="ml-auto rounded-sm bg-mint px-3 py-1.5 text-label font-semibold text-base transition-opacity hover:opacity-90"
        >
          Recarregar
        </Link>
      </div>

      {saldo && (
        <div className="rounded-md border border-line bg-raised px-4 py-3">
          <p className="text-label text-ink-dim">Saldo atual</p>
          <p className="tabular mt-0.5 text-title font-semibold text-ink">
            {formatarCreditos(saldo.saldo)}{" "}
            <span className="text-body font-normal text-ink-dim">créditos</span>
          </p>
        </div>
      )}

      {erro && (
        <p className="rounded-sm border border-danger/40 bg-danger-soft px-3 py-2 text-body text-danger">
          {erro}
        </p>
      )}

      {carregando && <p className="text-body text-ink-dim">Carregando…</p>}

      {!carregando && !erro && linhas.length === 0 && (
        <p className="rounded-md border border-line bg-raised p-6 text-body text-ink-dim">
          Nada por aqui ainda.
        </p>
      )}

      {linhas.length > 0 && (
        <div className="overflow-x-auto rounded-md border border-line bg-raised">
          <table className="w-full min-w-[34rem] text-body">
            <thead>
              <tr className="border-b border-line text-label text-ink-muted">
                <th className="px-4 py-2 text-left font-normal">Quando</th>
                <th className="px-4 py-2 text-left font-normal">O quê</th>
                <th className="px-4 py-2 text-right font-normal">Créditos</th>
                <th className="px-4 py-2 text-right font-normal">Saldo</th>
              </tr>
            </thead>
            <tbody>
              {linhas.map((l) => {
                const discreto = DISCRETO.includes(l.tipo);
                return (
                  <tr key={l.id} className="border-b border-line last:border-0">
                    <td className="tabular whitespace-nowrap px-4 py-2.5 text-ink-dim">
                      {formatarData(l.created_at)}
                    </td>
                    <td className="px-4 py-2.5">
                      <span className={discreto ? "text-ink-dim" : "text-ink"}>
                        {RÓTULO[l.tipo] ?? l.tipo}
                      </span>
                      {l.descricao && (
                        <span className="block text-label text-ink-muted">
                          {l.descricao}
                        </span>
                      )}
                    </td>
                    <td
                      className={`tabular whitespace-nowrap px-4 py-2.5 text-right font-medium ${
                        discreto
                          ? "text-ink-muted"
                          : l.amount > 0
                            ? "text-mint"
                            : "text-ink"
                      }`}
                    >
                      {l.amount > 0 ? "+" : ""}
                      {formatarCreditos(l.amount)}
                    </td>
                    <td className="tabular whitespace-nowrap px-4 py-2.5 text-right text-ink-dim">
                      {formatarCreditos(l.balance_after)}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
