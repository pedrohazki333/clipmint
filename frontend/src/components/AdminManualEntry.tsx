"use client";

import { useCallback, useEffect, useState } from "react";

import {
  createManualPayment,
  createManualSubscription,
  getAdminPayments,
  getApiErrorMessage,
  setPaymentStatus,
} from "@/lib/api";
import { formatarBRL } from "@/lib/creditos";
import type { PaymentAdmin } from "@/lib/types";

/**
 * Lançar à mão o que não passou pelo gateway.
 *
 * Pix recebido direto na chave, cortesia, cliente antigo em acordo de boca — num
 * negócio pequeno isso não é exceção rara, e sem um lugar para registrar esses
 * recebimentos o painel mostra um lucro menor que o real.
 *
 * Escreve nas MESMAS tabelas do webhook. O que distingue é a etiqueta `manual`
 * na lista abaixo.
 *
 * Duas escolhas de interface que vêm da regra do backend:
 *
 *   - **"entregar créditos" é uma caixa desmarcada.** Registrar receita e
 *     entregar crédito são coisas diferentes, e marcá-la por padrão daria
 *     crédito de graça toda vez que o dono só quisesse acertar o extrato.
 *   - **a referência do Pix é pedida com o motivo escrito.** É ela que faz o
 *     banco recusar o mesmo recebimento lançado duas vezes — o erro provável
 *     aqui é conferir o extrato e lançar de novo na semana seguinte.
 */

const CAMPO =
  "rounded-sm border border-line bg-inset px-2 py-1.5 text-body text-ink focus:border-mint focus:outline-none";

function Campo({
  rotulo,
  nota,
  ...props
}: { rotulo: string; nota?: string } & React.InputHTMLAttributes<HTMLInputElement>) {
  return (
    <label className="flex flex-col gap-1">
      <span className="text-label text-ink-muted">{rotulo}</span>
      <input className={CAMPO} {...props} />
      {nota && <span className="text-label text-ink-muted">{nota}</span>}
    </label>
  );
}

export default function AdminManualEntry({ onMudou }: { onMudou: () => void }) {
  const [pagamentos, setPagamentos] = useState<PaymentAdmin[]>([]);
  const [erro, setErro] = useState("");
  const [ok, setOk] = useState("");
  const [enviando, setEnviando] = useState(false);

  const [pag, setPag] = useState({
    email: "",
    valor_brl: "",
    taxa_brl: "",
    referencia: "",
    pago_em: "",
    conceder_creditos: false,
    creditos: "",
  });
  const [ass, setAss] = useState({
    email: "",
    plan_code: "",
    valor_brl: "",
    creditos_mes: "",
  });

  const carregar = useCallback(() => {
    getAdminPayments()
      .then(setPagamentos)
      .catch(() => setPagamentos([]));
  }, []);

  useEffect(() => carregar(), [carregar]);

  function avisar(mensagem: string) {
    setOk(mensagem);
    setErro("");
    setTimeout(() => setOk(""), 3000);
    carregar();
    onMudou();
  }

  async function lancarPagamento() {
    setEnviando(true);
    setErro("");
    try {
      await createManualPayment({
        email: pag.email.trim(),
        valor_brl: pag.valor_brl,
        taxa_brl: pag.taxa_brl || undefined,
        referencia: pag.referencia.trim() || undefined,
        pago_em: pag.pago_em ? new Date(pag.pago_em).toISOString() : undefined,
        conceder_creditos: pag.conceder_creditos,
        creditos: Number(pag.creditos || 0),
      });
      setPag({ ...pag, valor_brl: "", taxa_brl: "", referencia: "", creditos: "" });
      avisar("Pagamento lançado");
    } catch (err) {
      setErro(getApiErrorMessage(err, "Não foi possível lançar o pagamento."));
    } finally {
      setEnviando(false);
    }
  }

  async function lancarAssinatura() {
    setEnviando(true);
    setErro("");
    try {
      await createManualSubscription({
        email: ass.email.trim(),
        plan_code: ass.plan_code.trim(),
        valor_brl: ass.valor_brl,
        creditos_mes: Number(ass.creditos_mes || 0),
      });
      setAss({ email: "", plan_code: "", valor_brl: "", creditos_mes: "" });
      avisar("Assinatura lançada");
    } catch (err) {
      setErro(getApiErrorMessage(err, "Não foi possível lançar a assinatura."));
    } finally {
      setEnviando(false);
    }
  }

  async function mudar(id: string, status: "refunded" | "chargeback") {
    setErro("");
    try {
      await setPaymentStatus(id, status);
      avisar(status === "refunded" ? "Marcado como estorno" : "Marcado como chargeback");
    } catch (err) {
      setErro(getApiErrorMessage(err, "Não foi possível mudar o status."));
    }
  }

  return (
    <section className="flex flex-col gap-2">
      <div className="flex flex-wrap items-baseline gap-x-3">
        <h2 className="text-body font-medium text-ink">Lançamento manual</h2>
        <span className="text-label text-ink-muted">
          o que entrou fora do gateway
        </span>
      </div>

      <div className="flex flex-col gap-4 rounded-md border border-line bg-raised p-4">
        {/* ── Pagamento ─────────────────────────────────────────────────── */}
        <div className="flex flex-col gap-3">
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
            <Campo
              rotulo="E-mail da conta"
              value={pag.email}
              onChange={(e) => setPag({ ...pag, email: e.target.value })}
              placeholder="cliente@exemplo.com"
            />
            <Campo
              rotulo="Valor recebido"
              value={pag.valor_brl}
              onChange={(e) => setPag({ ...pag, valor_brl: e.target.value })}
              inputMode="decimal"
              placeholder="180.00"
              nota="BRL bruto"
            />
            <Campo
              rotulo="Taxa cobrada"
              value={pag.taxa_brl}
              onChange={(e) => setPag({ ...pag, taxa_brl: e.target.value })}
              inputMode="decimal"
              placeholder="opcional"
              nota="em branco = estimada pelo percentual"
            />
            <Campo
              rotulo="Referência do Pix"
              value={pag.referencia}
              onChange={(e) => setPag({ ...pag, referencia: e.target.value })}
              placeholder="E2E do comprovante"
              nota="informe e o mesmo Pix não entra duas vezes"
            />
            <Campo
              rotulo="Quando entrou"
              type="datetime-local"
              value={pag.pago_em}
              onChange={(e) => setPag({ ...pag, pago_em: e.target.value })}
              nota="em branco = agora"
            />
            <div className="flex flex-col gap-1">
              <label className="flex items-center gap-2 pt-5">
                <input
                  type="checkbox"
                  checked={pag.conceder_creditos}
                  onChange={(e) =>
                    setPag({ ...pag, conceder_creditos: e.target.checked })
                  }
                  className="h-4 w-4 accent-[var(--color-mint)]"
                />
                <span className="text-body text-ink">Entregar créditos</span>
              </label>
              {pag.conceder_creditos && (
                <input
                  className={CAMPO}
                  value={pag.creditos}
                  onChange={(e) => setPag({ ...pag, creditos: e.target.value })}
                  inputMode="numeric"
                  placeholder="quantos créditos"
                />
              )}
              <span className="text-label text-ink-muted">
                desmarcado = só registra a receita
              </span>
            </div>
          </div>
          <button
            type="button"
            onClick={lancarPagamento}
            disabled={enviando || !pag.email || !pag.valor_brl}
            className="self-start rounded-sm bg-mint px-3 py-1.5 text-body font-semibold text-base transition-opacity hover:opacity-90 disabled:opacity-50"
          >
            Lançar pagamento
          </button>
        </div>

        {/* ── Assinatura ────────────────────────────────────────────────── */}
        <div className="flex flex-col gap-3 border-t border-line pt-4">
          <p className="text-label text-ink-muted">
            Assinatura acordada fora do gateway — sem isso ela some do MRR.
          </p>
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
            <Campo
              rotulo="E-mail da conta"
              value={ass.email}
              onChange={(e) => setAss({ ...ass, email: e.target.value })}
            />
            <Campo
              rotulo="Plano"
              value={ass.plan_code}
              onChange={(e) => setAss({ ...ass, plan_code: e.target.value })}
              placeholder="acordo"
            />
            <Campo
              rotulo="Valor mensal"
              value={ass.valor_brl}
              onChange={(e) => setAss({ ...ass, valor_brl: e.target.value })}
              inputMode="decimal"
            />
            <Campo
              rotulo="Créditos por mês"
              value={ass.creditos_mes}
              onChange={(e) => setAss({ ...ass, creditos_mes: e.target.value })}
              inputMode="numeric"
            />
          </div>
          <button
            type="button"
            onClick={lancarAssinatura}
            disabled={enviando || !ass.email || !ass.plan_code || !ass.valor_brl}
            className="self-start rounded-sm border border-line px-3 py-1.5 text-body text-ink-dim transition-colors hover:border-line-strong hover:text-ink disabled:opacity-50"
          >
            Lançar assinatura
          </button>
        </div>

        {ok && <p className="text-label text-mint">{ok}</p>}
        {erro && (
          <p className="rounded-sm border border-danger/40 bg-danger-soft px-3 py-2 text-body text-danger">
            {erro}
          </p>
        )}
      </div>

      {/* ── Últimos pagamentos ──────────────────────────────────────────── */}
      {pagamentos.length > 0 && (
        <div className="overflow-x-auto rounded-md border border-line bg-raised">
          <table className="w-full min-w-[34rem] text-body">
            <thead>
              <tr className="border-b border-line text-label text-ink-muted">
                <th className="px-4 py-2 text-left font-normal">Quando</th>
                <th className="px-4 py-2 text-left font-normal">Origem</th>
                <th className="px-4 py-2 text-right font-normal">Valor</th>
                <th className="px-4 py-2 text-left font-normal">Status</th>
                <th className="px-4 py-2" />
              </tr>
            </thead>
            <tbody>
              {pagamentos.map((p) => (
                <tr key={p.id} className="border-b border-line last:border-0">
                  <td className="tabular whitespace-nowrap px-4 py-2 text-ink-dim">
                    {(p.paid_at ?? p.created_at ?? "").slice(0, 10)}
                  </td>
                  <td className="px-4 py-2">
                    <span
                      className={`rounded-sm border px-1.5 text-label ${
                        p.gateway === "manual"
                          ? "border-line-strong text-ink-dim"
                          : "border-mint text-mint"
                      }`}
                    >
                      {p.gateway}
                    </span>
                  </td>
                  <td className="tabular px-4 py-2 text-right text-ink">
                    {formatarBRL(p.amount_brl_gross)}
                  </td>
                  <td
                    className={`px-4 py-2 text-label ${
                      p.status === "paid"
                        ? "text-mint"
                        : p.status === "pending"
                          ? "text-ink-muted"
                          : "text-danger"
                    }`}
                  >
                    {p.status}
                  </td>
                  <td className="px-4 py-2 text-right">
                    {p.status === "paid" && (
                      <span className="flex justify-end gap-2">
                        <button
                          type="button"
                          onClick={() => mudar(p.id, "refunded")}
                          className="text-label text-ink-muted hover:text-danger"
                        >
                          estorno
                        </button>
                        <button
                          type="button"
                          onClick={() => mudar(p.id, "chargeback")}
                          className="text-label text-ink-muted hover:text-danger"
                        >
                          chargeback
                        </button>
                      </span>
                    )}
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
