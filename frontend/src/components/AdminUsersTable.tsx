"use client";

import { formatarBRL } from "@/lib/creditos";
import type { UsuarioNoPeriodo } from "@/lib/types";

/**
 * Quem paga contra quem custa, no período.
 *
 * É a tabela que vai embasar a política de rate limit: o cliente deficitário
 * não aparece no total do mês, que pode estar ótimo, mas aparece aqui.
 *
 * Vem ordenada do pior resultado para o melhor — quem precisa de decisão fica
 * no topo, e não na página 3. O destaque do deficitário é uma tarja na lateral
 * mais o rótulo escrito, nunca só a cor da linha.
 */
export default function AdminUsersTable({
  linhas,
}: {
  linhas: UsuarioNoPeriodo[];
}) {
  const deficitarios = linhas.filter((l) => l.deficitario).length;

  return (
    <section className="flex flex-col gap-2">
      <div className="flex flex-wrap items-baseline gap-x-3">
        <h2 className="text-body font-medium text-ink">Por usuário</h2>
        {deficitarios > 0 && (
          <span className="text-label text-danger">
            {deficitarios} custa{deficitarios === 1 ? "" : "m"} mais do que
            paga{deficitarios === 1 ? "" : "m"}
          </span>
        )}
      </div>

      {linhas.length === 0 ? (
        <p className="rounded-md border border-line bg-raised p-6 text-body text-ink-dim">
          Nenhum movimento de usuário neste mês.
        </p>
      ) : (
        <div className="overflow-x-auto rounded-md border border-line bg-raised">
          <table className="w-full min-w-[36rem] text-body">
            <thead>
              <tr className="border-b border-line text-label text-ink-muted">
                <th className="px-4 py-2 text-left font-normal">Conta</th>
                <th className="px-4 py-2 text-right font-normal">Vídeos</th>
                <th className="px-4 py-2 text-right font-normal">Pagou</th>
                <th className="px-4 py-2 text-right font-normal">Custou</th>
                <th className="px-4 py-2 text-right font-normal">Resultado</th>
              </tr>
            </thead>
            <tbody>
              {linhas.map((l) => (
                <tr
                  key={l.user_id}
                  className={`border-b border-line last:border-0 ${
                    l.deficitario ? "bg-danger-soft" : ""
                  }`}
                >
                  <td className="px-4 py-2">
                    <span className="flex items-center gap-2">
                      {/* Tarja + rótulo: o destaque não pode ser só a cor. */}
                      {l.deficitario && (
                        <span
                          aria-hidden
                          className="h-4 w-0.5 flex-shrink-0 bg-danger"
                        />
                      )}
                      <span className="truncate text-ink">{l.email}</span>
                      {l.deficitario && (
                        <span className="flex-shrink-0 rounded-sm border border-danger px-1.5 text-label text-danger">
                          prejuízo
                        </span>
                      )}
                    </span>
                  </td>
                  <td className="tabular px-4 py-2 text-right text-ink-dim">
                    {l.videos}
                  </td>
                  <td className="tabular px-4 py-2 text-right text-ink">
                    {formatarBRL(l.receita_brl)}
                  </td>
                  <td className="tabular px-4 py-2 text-right text-ink">
                    {formatarBRL(l.custo_brl)}
                  </td>
                  <td
                    className={`tabular px-4 py-2 text-right font-medium ${
                      l.deficitario ? "text-danger" : "text-mint"
                    }`}
                  >
                    {Number(l.resultado_brl) >= 0 ? "+" : "−"}
                    {formatarBRL(Math.abs(Number(l.resultado_brl)))}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}
