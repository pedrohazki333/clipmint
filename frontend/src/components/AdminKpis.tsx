"use client";

import { formatarBRL } from "@/lib/creditos";
import type { Overview } from "@/lib/types";

/**
 * A linha de números do painel.
 *
 * Cada bloco traz o mês corrente E a variação contra o anterior, porque um
 * número sozinho não diz se melhorou: R$ 400 de lucro é ótimo depois de R$ 100
 * e péssimo depois de R$ 900.
 *
 * O lucro vem primeiro e maior — é a pergunta que faz alguém abrir esta tela.
 * O resto é a decomposição dele, na ordem da fórmula: receita, menos os custos,
 * menos imposto e taxas.
 */

function variacao(atual: string, anterior: string): number | null {
  const a = Number(atual);
  const b = Number(anterior);
  if (!Number.isFinite(a) || !Number.isFinite(b) || b === 0) return null;
  return ((a - b) / Math.abs(b)) * 100;
}

function Delta({ atual, anterior }: { atual: string; anterior: string }) {
  const v = variacao(atual, anterior);
  if (v === null) return null;
  const subiu = v >= 0;
  return (
    <span
      className={`tabular text-label ${subiu ? "text-mint" : "text-danger"}`}
      title={`Mês anterior: ${formatarBRL(anterior)}`}
    >
      {/* O sinal vai escrito, não só na cor: verde e vermelho ficam a ΔE 6,5
          em deuteranopia, e o leitor não pode depender do matiz. */}
      {subiu ? "▲" : "▼"} {subiu ? "+" : ""}
      {v.toFixed(1)}%
    </span>
  );
}

function Bloco({
  rotulo,
  valor,
  atual,
  anterior,
  destaque = false,
  tom = "neutro",
  nota,
}: {
  rotulo: string;
  valor: string;
  atual?: string;
  anterior?: string;
  destaque?: boolean;
  tom?: "neutro" | "bom" | "ruim";
  nota?: string;
}) {
  const cor =
    tom === "bom" ? "text-mint" : tom === "ruim" ? "text-danger" : "text-ink";
  return (
    <div
      className={`flex flex-col gap-0.5 rounded-md border bg-raised px-4 py-3 ${
        destaque ? "border-line-strong" : "border-line"
      }`}
    >
      <span className="text-label text-ink-muted">{rotulo}</span>
      <span
        className={`tabular font-semibold ${cor} ${
          destaque ? "text-[1.6rem] leading-tight" : "text-title"
        }`}
      >
        {valor}
      </span>
      <div className="flex items-baseline gap-2">
        {atual !== undefined && anterior !== undefined && (
          <Delta atual={atual} anterior={anterior} />
        )}
        {nota && <span className="text-label text-ink-muted">{nota}</span>}
      </div>
    </div>
  );
}

export default function AdminKpis({
  atual,
  anterior,
}: {
  atual: Overview;
  anterior: Overview;
}) {
  const lucro = Number(atual.lucro_liquido_brl);

  return (
    <div className="flex flex-col gap-3">
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <Bloco
          rotulo="Lucro líquido"
          valor={formatarBRL(atual.lucro_liquido_brl)}
          atual={atual.lucro_liquido_brl}
          anterior={anterior.lucro_liquido_brl}
          destaque
          tom={lucro >= 0 ? "bom" : "ruim"}
          nota={`margem ${atual.margem_liquida_pct}%`}
        />
        <Bloco
          rotulo="Receita bruta"
          valor={formatarBRL(atual.receita_bruta_brl)}
          atual={atual.receita_bruta_brl}
          anterior={anterior.receita_bruta_brl}
          nota={`${atual.pagamentos} pagamento${atual.pagamentos === 1 ? "" : "s"}`}
        />
        <Bloco
          rotulo="Custo variável"
          valor={formatarBRL(atual.custo_variavel_brl)}
          atual={atual.custo_variavel_brl}
          anterior={anterior.custo_variavel_brl}
          nota={`${atual.videos_processados} vídeo${atual.videos_processados === 1 ? "" : "s"}`}
        />
        <Bloco
          rotulo="MRR"
          valor={formatarBRL(atual.mrr_brl)}
          atual={atual.mrr_brl}
          anterior={anterior.mrr_brl}
          nota={`${atual.assinantes_ativos} assinante${atual.assinantes_ativos === 1 ? "" : "s"}`}
        />
      </div>

      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <Bloco
          rotulo="Custo fixo"
          valor={formatarBRL(atual.custo_fixo_brl)}
          nota="mês inteiro"
        />
        <Bloco
          rotulo="Imposto estimado"
          valor={formatarBRL(atual.imposto_brl)}
          nota={`${atual.imposto_pct}% da receita`}
        />
        <Bloco
          rotulo="Taxas do gateway"
          valor={formatarBRL(atual.taxas_gateway_brl)}
          nota={
            atual.taxas_estimadas
              ? `${atual.taxas_estimadas} estimada${atual.taxas_estimadas === 1 ? "" : "s"}`
              : "informadas"
          }
        />
        <Bloco
          rotulo="Perdido em job devolvido"
          valor={formatarBRL(atual.prejuizo_devolvido_brl)}
          tom={Number(atual.prejuizo_devolvido_brl) > 0 ? "ruim" : "neutro"}
          nota={`${atual.videos_devolvidos} vídeo${atual.videos_devolvidos === 1 ? "" : "s"}`}
        />
      </div>

      <div className="grid gap-3 sm:grid-cols-3">
        <Bloco
          rotulo="Novos assinantes"
          valor={String(atual.novos_no_mes)}
          nota="no mês"
        />
        <Bloco
          rotulo="Cancelamentos"
          valor={String(atual.cancelados_no_mes)}
          tom={atual.cancelados_no_mes > 0 ? "ruim" : "neutro"}
          nota="no mês"
        />
        <Bloco
          rotulo="Churn"
          valor={`${atual.churn_pct}%`}
          nota="sobre a base do início do mês"
        />
      </div>
    </div>
  );
}
