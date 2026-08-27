"use client";

import { useCallback, useEffect, useState } from "react";

import AdminKpis from "@/components/AdminKpis";
import AdminManualEntry from "@/components/AdminManualEntry";
import AdminRatesForm from "@/components/AdminRatesForm";
import AdminSeriesChart from "@/components/AdminSeriesChart";
import AdminUsersTable from "@/components/AdminUsersTable";
import {
  getAdminOverview,
  getAdminSeries,
  getAdminUsers,
  getApiErrorMessage,
  getCostConfig,
} from "@/lib/api";
import type {
  CostConfig,
  OverviewComparado,
  SerieDia,
  UsuarioNoPeriodo,
} from "@/lib/types";

/**
 * O painel do dono.
 *
 * Não aparece na navegação de ninguém: quem entra aqui digita a URL, e o
 * backend confere `is_owner` em cada uma das quatro chamadas. Se um usuário
 * comum chegar, ele vê a mensagem de área restrita — não uma tela quebrada nem,
 * pior, os números.
 *
 * A ordem da página é a ordem da pergunta: primeiro o resultado do mês, depois
 * o desenho dele no tempo, depois quem está dando prejuízo, e por último as
 * tarifas que produziram tudo isso.
 */

function mesAtual(): string {
  // O mês corrente em São Paulo, que é a fronteira que o backend usa.
  const agora = new Date();
  const local = new Date(
    agora.toLocaleString("en-US", { timeZone: "America/Sao_Paulo" }),
  );
  return `${local.getFullYear()}-${String(local.getMonth() + 1).padStart(2, "0")}`;
}

export default function AdminPage() {
  const [mes, setMes] = useState(mesAtual);
  const [visao, setVisao] = useState<OverviewComparado | null>(null);
  const [serie, setSerie] = useState<SerieDia[]>([]);
  const [usuarios, setUsuarios] = useState<UsuarioNoPeriodo[]>([]);
  const [config, setConfig] = useState<CostConfig | null>(null);
  const [carregando, setCarregando] = useState(true);
  const [erro, setErro] = useState("");

  const carregar = useCallback(async () => {
    setCarregando(true);
    setErro("");
    try {
      const [v, s, u, c] = await Promise.all([
        getAdminOverview(mes),
        getAdminSeries(mes),
        getAdminUsers(mes),
        getCostConfig(),
      ]);
      setVisao(v);
      setSerie(s);
      setUsuarios(u);
      setConfig(c);
    } catch (err) {
      setErro(getApiErrorMessage(err, "Não foi possível carregar o painel."));
    } finally {
      setCarregando(false);
    }
  }, [mes]);

  useEffect(() => {
    carregar();
  }, [carregar]);

  return (
    <div className="flex flex-col gap-6">
      <div className="flex flex-wrap items-baseline gap-x-3 gap-y-2">
        <h1 className="text-title font-semibold text-ink">Painel</h1>
        <span className="text-label text-ink-muted">
          receita, custo e lucro · fuso de São Paulo
        </span>
        <label className="ml-auto flex items-center gap-2">
          <span className="text-label text-ink-muted">Mês</span>
          <input
            type="month"
            value={mes}
            onChange={(e) => setMes(e.target.value || mesAtual())}
            className="tabular rounded-sm border border-line bg-inset px-2 py-1 text-body text-ink focus:border-mint focus:outline-none"
          />
        </label>
      </div>

      {erro && (
        <p className="rounded-md border border-danger/40 bg-danger-soft px-4 py-3 text-body text-danger">
          {erro}
        </p>
      )}

      {carregando && !visao && (
        <p className="text-body text-ink-dim">Carregando…</p>
      )}

      {visao && (
        <>
          <AdminKpis atual={visao.atual} anterior={visao.anterior} />

          {/* Os avisos ficam ENTRE os números e o gráfico, não num rodapé: quem
              lê "lucro de R$ 753" precisa saber ali que parte é estimativa. */}
          {visao.atual.avisos.length > 0 && (
            <ul className="flex flex-col gap-1 rounded-md border border-line bg-inset px-4 py-3">
              {visao.atual.avisos.map((a) => (
                <li key={a} className="text-label text-ink-muted">
                  {a}
                </li>
              ))}
            </ul>
          )}

          <AdminSeriesChart serie={serie} />
          <AdminUsersTable linhas={usuarios} />
          {/* Recarrega os números depois de um lançamento: o painel tem que
              refletir na hora o que acabou de ser registrado. */}
          <AdminManualEntry onMudou={carregar} />
          {config && <AdminRatesForm config={config} onSalvo={setConfig} />}
        </>
      )}
    </div>
  );
}
