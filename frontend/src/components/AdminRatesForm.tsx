"use client";

import { useState } from "react";

import { getApiErrorMessage, updateCostConfig } from "@/lib/api";
import type { CostConfig } from "@/lib/types";

/**
 * As tarifas, editáveis sem deploy.
 *
 * Câmbio muda toda semana, a Anthropic reprecifica, o contador confirma o
 * imposto. Se isso morasse em variável de ambiente, cada ajuste seria um
 * reinício do servidor no meio do expediente.
 *
 * Alterar aqui **não reescreve histórico**: cada vídeo já processado congelou as
 * tarifas que usou. O que muda é a projeção e o custo dos vídeos seguintes — e o
 * aviso abaixo diz isso, porque é o medo natural de quem vai clicar em salvar.
 */

const CAMPOS: { chave: keyof CostConfig; rotulo: string; sufixo: string }[] = [
  { chave: "assemblyai_usd_per_min", rotulo: "Transcrição", sufixo: "USD / min" },
  { chave: "storage_usd_per_video", rotulo: "Storage", sufixo: "USD / vídeo" },
  { chave: "fx_usd_brl", rotulo: "Dólar", sufixo: "BRL" },
  { chave: "fx_eur_brl", rotulo: "Euro", sufixo: "BRL" },
  { chave: "fixed_cost_brl_month", rotulo: "Custo fixo", sufixo: "BRL / mês" },
  { chave: "tax_pct_on_revenue", rotulo: "Imposto", sufixo: "% da receita" },
  { chave: "gateway_fee_pct", rotulo: "Taxa do gateway", sufixo: "% do bruto" },
];

export default function AdminRatesForm({
  config,
  onSalvo,
}: {
  config: CostConfig;
  onSalvo: (novo: CostConfig) => void;
}) {
  const [valores, setValores] = useState<Record<string, string>>(() =>
    Object.fromEntries(CAMPOS.map((c) => [c.chave, String(config[c.chave])])),
  );
  const [salvando, setSalvando] = useState(false);
  const [erro, setErro] = useState("");
  const [ok, setOk] = useState(false);

  async function salvar() {
    setSalvando(true);
    setErro("");
    setOk(false);
    try {
      const novo = await updateCostConfig(valores);
      onSalvo(novo);
      setOk(true);
      setTimeout(() => setOk(false), 3000);
    } catch (err) {
      setErro(getApiErrorMessage(err, "Não foi possível salvar as tarifas."));
    } finally {
      setSalvando(false);
    }
  }

  return (
    <section className="flex flex-col gap-2">
      <h2 className="text-body font-medium text-ink">Tarifas</h2>

      <div className="flex flex-col gap-4 rounded-md border border-line bg-raised p-4">
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
          {CAMPOS.map((c) => (
            <label key={c.chave} className="flex flex-col gap-1">
              <span className="text-label text-ink-muted">{c.rotulo}</span>
              <input
                value={valores[c.chave] ?? ""}
                onChange={(e) =>
                  setValores({ ...valores, [c.chave]: e.target.value })
                }
                inputMode="decimal"
                className="tabular rounded-sm border border-line bg-inset px-2 py-1.5 text-body text-ink focus:border-mint focus:outline-none"
              />
              <span className="text-label text-ink-muted">{c.sufixo}</span>
            </label>
          ))}
        </div>

        <div className="rounded-sm border border-line bg-inset px-3 py-2">
          <p className="text-label text-ink-muted">
            Tarifas de modelo (USD por milhão de tokens)
          </p>
          <ul className="mt-1 flex flex-wrap gap-x-4 gap-y-1">
            {Object.entries(config.llm_rates ?? {}).map(([modelo, r]) => (
              <li key={modelo} className="tabular text-label text-ink-dim">
                {modelo}: {r.input} entrada / {r.output} saída
              </li>
            ))}
          </ul>
        </div>

        <p className="text-label text-ink-muted">
          Salvar aqui <strong className="text-ink-dim">não reescreve o
          histórico</strong>: cada vídeo já processado congelou as tarifas que
          usou. Muda a projeção e os vídeos seguintes.
        </p>

        <div className="flex items-center gap-3">
          <button
            type="button"
            onClick={salvar}
            disabled={salvando}
            className="rounded-sm bg-mint px-3 py-1.5 text-body font-semibold text-base transition-opacity hover:opacity-90 disabled:opacity-50"
          >
            {salvando ? "Salvando…" : "Salvar tarifas"}
          </button>
          {ok && <span className="text-label text-mint">Salvo</span>}
          {erro && <span className="text-label text-danger">{erro}</span>}
        </div>
      </div>
    </section>
  );
}
