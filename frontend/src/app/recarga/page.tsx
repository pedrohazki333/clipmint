"use client";

import Link from "next/link";
import { useCallback, useEffect, useRef, useState } from "react";

import {
  cancelSubscription,
  createTopup,
  getApiErrorMessage,
  getCatalog,
  getPaymentStatus,
  getSubscription,
  subscribe,
} from "@/lib/api";
import { avisarSaldoMudou, formatarBRL, formatarCreditos, useSaldo } from "@/lib/creditos";
import type { Catalog, Subscription, Topup } from "@/lib/types";

/**
 * Recarga: pacotes de crédito por Pix, e os planos de assinatura.
 *
 * O preço de cada pacote vem PRONTO do servidor (`/billing/catalog`). A tela
 * não multiplica crédito por preço unitário em lugar nenhum — se ela fizesse a
 * própria conta, ela e a cobrança discordariam no primeiro pacote com desconto,
 * e quem discorda por último é a fatura.
 *
 * O acompanhamento do pagamento é por polling e não por espera do webhook: em
 * desenvolvimento o Mercado Pago não alcança um localhost, e mesmo em produção
 * uma notificação pode demorar ou se perder. O endpoint consultado sincroniza
 * com o gateway, então a tela resolve sozinha.
 */

const INTERVALO_MS = 3000;

export default function RecargaPage() {
  const { saldo } = useSaldo();
  const [catalogo, setCatalogo] = useState<Catalog | null>(null);
  const [erro, setErro] = useState("");
  const [gerando, setGerando] = useState<number | null>(null);
  const [cobranca, setCobranca] = useState<Topup | null>(null);
  const [pago, setPago] = useState(false);
  const [copiado, setCopiado] = useState(false);
  const timer = useRef<ReturnType<typeof setInterval> | null>(null);

  const [assinatura, setAssinatura] = useState<Subscription | null>(null);
  const [assinando, setAssinando] = useState<string | null>(null);
  const [cancelando, setCancelando] = useState(false);

  useEffect(() => {
    getCatalog()
      .then(setCatalogo)
      .catch((err) =>
        setErro(getApiErrorMessage(err, "Não foi possível carregar os pacotes.")),
      );
  }, []);

  // Esta é a página de volta do gateway (`back_url`): quem acabou de autorizar
  // o cartão cai aqui, e a consulta sincroniza o status. Sem isso a pessoa
  // voltaria e continuaria vendo "aguardando autorização".
  const carregarAssinatura = useCallback(() => {
    getSubscription()
      .then((s) => {
        setAssinatura(s);
        if (s?.status === "active") avisarSaldoMudou();
      })
      .catch(() => setAssinatura(null));
  }, []);

  useEffect(() => {
    carregarAssinatura();
  }, [carregarAssinatura]);

  async function assinar(planCode: string) {
    setErro("");
    setAssinando(planCode);
    try {
      const nova = await subscribe(planCode);
      if (nova.init_point) {
        // O cartão é digitado NA PÁGINA DO MERCADO PAGO. Sair daqui é o
        // recurso, não um efeito colateral.
        window.location.href = nova.init_point;
        return;
      }
      setAssinatura(nova);
    } catch (err) {
      setErro(getApiErrorMessage(err, "Não foi possível iniciar a assinatura."));
    } finally {
      setAssinando(null);
    }
  }

  async function cancelar() {
    setErro("");
    setCancelando(true);
    try {
      setAssinatura(await cancelSubscription());
    } catch (err) {
      setErro(getApiErrorMessage(err, "Não foi possível cancelar."));
    } finally {
      setCancelando(false);
    }
  }

  const pararPolling = useCallback(() => {
    if (timer.current) {
      clearInterval(timer.current);
      timer.current = null;
    }
  }, []);

  useEffect(() => pararPolling, [pararPolling]);

  async function comprar(creditos: number) {
    setErro("");
    setPago(false);
    setGerando(creditos);
    try {
      const nova = await createTopup(creditos);
      setCobranca(nova);

      pararPolling();
      timer.current = setInterval(async () => {
        try {
          const status = await getPaymentStatus(nova.payment_id);
          if (status.status === "paid") {
            pararPolling();
            setPago(true);
            // O saldo do topo tem que mudar no mesmo instante em que a tela diz
            // que foi pago; senão a pessoa recarrega a página para conferir.
            avisarSaldoMudou();
          }
        } catch {
          /* uma consulta que falhou não cancela a compra; a próxima tenta */
        }
      }, INTERVALO_MS);
    } catch (err) {
      setErro(getApiErrorMessage(err, "Não foi possível gerar o Pix."));
    } finally {
      setGerando(null);
    }
  }

  async function copiar() {
    if (!cobranca?.qr_code) return;
    try {
      await navigator.clipboard.writeText(cobranca.qr_code);
      setCopiado(true);
      setTimeout(() => setCopiado(false), 2000);
    } catch {
      /* sem permissão de área de transferência: o código continua à vista */
    }
  }

  return (
    <div className="flex flex-col gap-5">
      <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
        <h1 className="text-title font-semibold text-ink">Recarregar</h1>
        <span className="text-label text-ink-muted">
          1 crédito = 1 minuto de vídeo de origem
        </span>
        <Link
          href="/creditos"
          className="ml-auto text-label text-ink-dim transition-colors hover:text-ink"
        >
          Ver extrato
        </Link>
      </div>

      {saldo && (
        <p className="text-body text-ink-dim">
          Saldo atual:{" "}
          <span className="tabular font-medium text-ink">
            {formatarCreditos(saldo.saldo)}
          </span>{" "}
          créditos
        </p>
      )}

      {erro && (
        <p className="rounded-sm border border-danger/40 bg-danger-soft px-3 py-2 text-body text-danger">
          {erro}
        </p>
      )}

      {/* ── O Pix em andamento ────────────────────────────────────────────── */}
      {cobranca && (
        <div className="rounded-md border border-line bg-raised p-4 sm:p-6">
          {pago ? (
            <div className="flex flex-col items-start gap-3">
              <p className="text-title font-semibold text-mint">
                Pagamento confirmado
              </p>
              <p className="text-body text-ink">
                {formatarCreditos(cobranca.creditos)} créditos entraram na sua
                conta.
              </p>
              <div className="flex gap-2">
                <Link
                  href="/"
                  className="rounded-sm bg-mint px-3 py-1.5 text-body font-semibold text-base transition-opacity hover:opacity-90"
                >
                  Gerar clips
                </Link>
                <button
                  type="button"
                  onClick={() => setCobranca(null)}
                  className="rounded-sm border border-line px-3 py-1.5 text-body text-ink-dim transition-colors hover:border-line-strong hover:text-ink"
                >
                  Comprar mais
                </button>
              </div>
            </div>
          ) : (
            <div className="flex flex-col gap-4 sm:flex-row sm:items-start">
              {cobranca.qr_code_base64 && (
                /* eslint-disable-next-line @next/next/no-img-element */
                <img
                  src={`data:image/png;base64,${cobranca.qr_code_base64}`}
                  alt="QR code do Pix"
                  className="h-44 w-44 flex-shrink-0 rounded-sm bg-white p-2"
                />
              )}
              <div className="min-w-0 flex-1">
                <p className="text-body text-ink">
                  {formatarCreditos(cobranca.creditos)} créditos por{" "}
                  <span className="tabular font-medium">
                    {formatarBRL(cobranca.valor_brl)}
                  </span>
                </p>
                <p className="mt-1 text-label text-ink-muted">
                  Pague pelo app do seu banco. A tela se atualiza sozinha quando
                  o pagamento cair.
                </p>

                {cobranca.qr_code && (
                  <>
                    <p className="mt-3 break-all rounded-sm border border-line bg-inset px-3 py-2 font-mono text-label text-ink-dim">
                      {cobranca.qr_code}
                    </p>
                    <button
                      type="button"
                      onClick={copiar}
                      className="mt-2 rounded-sm border border-line px-3 py-1.5 text-label text-ink-dim transition-colors hover:border-line-strong hover:text-ink"
                    >
                      {copiado ? "Copiado" : "Copiar código"}
                    </button>
                  </>
                )}

                <p className="mt-3 flex items-center gap-2 text-label text-ink-muted">
                  <span
                    aria-hidden
                    className="h-1.5 w-1.5 animate-pulse rounded-full bg-running"
                  />
                  Aguardando pagamento…
                </p>
              </div>
            </div>
          )}
        </div>
      )}

      {/* ── Pacotes ───────────────────────────────────────────────────────── */}
      {!cobranca && catalogo && (
        <section>
          <h2 className="mb-2 text-body font-medium text-ink">
            Pacotes avulsos
          </h2>
          <div className="grid gap-3 sm:grid-cols-3">
            {catalogo.pacotes.map((p) => (
              <button
                key={p.creditos}
                type="button"
                onClick={() => comprar(p.creditos)}
                disabled={gerando !== null}
                className="flex flex-col items-start rounded-md border border-line bg-raised p-4 text-left transition-colors hover:border-mint disabled:opacity-50"
              >
                <span className="tabular text-title font-semibold text-ink">
                  {formatarCreditos(p.creditos)}
                </span>
                <span className="text-label text-ink-muted">créditos</span>
                <span className="tabular mt-2 text-body font-medium text-mint">
                  {gerando === p.creditos
                    ? "Gerando Pix…"
                    : formatarBRL(p.preco_brl)}
                </span>
                <span className="mt-0.5 text-label text-ink-muted">
                  ~{formatarCreditos(Math.floor(p.creditos / 60))} h de vídeo
                </span>
              </button>
            ))}
          </div>
        </section>
      )}

      {/* ── Assinatura em vigor ───────────────────────────────────────────── */}
      {!cobranca && assinatura && assinatura.status !== "canceled" && (
        <section className="rounded-md border border-mint bg-mint-soft p-4">
          {assinatura.status === "pending" ? (
            <>
              <p className="text-body font-medium text-ink">
                Assinatura aguardando autorização
              </p>
              <p className="mt-1 text-label text-ink-dim">
                Falta autorizar o cartão na página do Mercado Pago. Nada é
                cobrado até você concluir.
              </p>
              <div className="mt-3 flex flex-wrap gap-2">
                {assinatura.init_point && (
                  <a
                    href={assinatura.init_point}
                    className="rounded-sm bg-mint px-3 py-1.5 text-label font-semibold text-base transition-opacity hover:opacity-90"
                  >
                    Continuar autorização
                  </a>
                )}
                <button
                  type="button"
                  onClick={cancelar}
                  disabled={cancelando}
                  className="rounded-sm border border-line px-3 py-1.5 text-label text-ink-dim transition-colors hover:border-line-strong hover:text-ink disabled:opacity-50"
                >
                  {cancelando ? "Cancelando…" : "Desistir"}
                </button>
              </div>
            </>
          ) : (
            <>
              <p className="text-body font-medium text-ink">
                Assinatura ativa —{" "}
                <span className="tabular">
                  {formatarCreditos(assinatura.creditos_mes)}
                </span>{" "}
                créditos por mês
              </p>
              <p className="tabular mt-1 text-label text-ink-dim">
                {formatarBRL(assinatura.valor_brl)} /mês
              </p>
              <button
                type="button"
                onClick={cancelar}
                disabled={cancelando}
                className="mt-3 rounded-sm border border-line px-3 py-1.5 text-label text-ink-dim transition-colors hover:border-line-strong hover:text-ink disabled:opacity-50"
              >
                {cancelando ? "Cancelando…" : "Cancelar assinatura"}
              </button>
            </>
          )}
        </section>
      )}

      {/* ── Planos ────────────────────────────────────────────────────────── */}
      {!cobranca &&
        catalogo &&
        catalogo.planos.length > 0 &&
        (!assinatura || assinatura.status === "canceled") && (
          <section>
            <h2 className="mb-2 text-body font-medium text-ink">
              Assinatura mensal
            </h2>
            <p className="mb-3 text-label text-ink-muted">
              Créditos todo mês, a um preço melhor por crédito. O cartão é
              digitado na página do Mercado Pago — não passa por aqui.
            </p>
            <div className="grid gap-3 sm:grid-cols-2">
              {catalogo.planos.map((pl) => (
                <div
                  key={pl.code}
                  className="flex flex-col items-start rounded-md border border-line bg-raised p-4"
                >
                  <p className="text-body font-medium text-ink">{pl.nome}</p>
                  <p className="tabular mt-1 text-title font-semibold text-ink">
                    {formatarBRL(pl.valor_brl)}
                    <span className="text-label font-normal text-ink-muted">
                      {" "}
                      /mês
                    </span>
                  </p>
                  <p className="tabular mt-0.5 text-label text-ink-dim">
                    {formatarCreditos(pl.creditos_mes)} créditos por mês
                  </p>
                  <button
                    type="button"
                    onClick={() => assinar(pl.code)}
                    disabled={assinando !== null}
                    className="mt-3 rounded-sm bg-mint px-3 py-1.5 text-label font-semibold text-base transition-opacity hover:opacity-90 disabled:opacity-50"
                  >
                    {assinando === pl.code ? "Abrindo…" : "Assinar"}
                  </button>
                </div>
              ))}
            </div>
          </section>
        )}
    </div>
  );
}
