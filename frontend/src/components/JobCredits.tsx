"use client";

import Link from "next/link";

import { formatarCreditos } from "@/lib/creditos";
import type { JobDetail } from "@/lib/types";

/**
 * O que este job custou.
 *
 * Três momentos, três mensagens diferentes, porque a pergunta muda: enquanto
 * roda é "quanto está preso?"; quando termina é "quanto saiu e com quanto
 * fiquei?"; quando falha é "fui cobrado por isso?" — e essa última merece
 * resposta explícita, senão a pessoa assume que sim.
 *
 * Some por completo quando não há cobrança (versão pessoal, ou job criado antes
 * dela): um "0 créditos" ali seria mentira, não informação.
 */
export default function JobCredits({ job }: { job: JobDetail }) {
  const reservado = job.creditos_reservados;
  if (reservado == null) return null;

  const cobrado = job.creditos_cobrados;
  const saldo = job.saldo;
  const rodando = job.status !== "done" && job.status !== "error";

  return (
    <p className="text-label text-ink-muted">
      {rodando && (
        <>
          <span className="tabular text-ink-dim">
            {formatarCreditos(reservado)}
          </span>{" "}
          créditos reservados para este vídeo. O que sobrar volta quando
          terminar.
        </>
      )}

      {!rodando && cobrado != null && (
        <>
          Custou{" "}
          <span className="tabular font-medium text-ink-dim">
            {formatarCreditos(cobrado)}
          </span>{" "}
          créditos
          {cobrado < reservado && (
            <>
              {" "}
              — {formatarCreditos(reservado - cobrado)} da reserva voltaram
            </>
          )}
          {saldo != null && (
            <>
              {" · "}saldo:{" "}
              <span className="tabular text-ink-dim">
                {formatarCreditos(saldo)}
              </span>
            </>
          )}
        </>
      )}

      {!rodando && cobrado == null && (
        <>
          Nada foi cobrado por este job
          {saldo != null && (
            <>
              {" · "}saldo:{" "}
              <span className="tabular text-ink-dim">
                {formatarCreditos(saldo)}
              </span>
            </>
          )}
          .{" "}
          <Link href="/creditos" className="text-mint hover:text-mint-strong">
            Ver extrato
          </Link>
        </>
      )}
    </p>
  );
}
