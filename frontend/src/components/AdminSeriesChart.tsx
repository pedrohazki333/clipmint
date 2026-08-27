"use client";

import { useState } from "react";

import { formatarBRL } from "@/lib/creditos";
import type { SerieDia } from "@/lib/types";

/**
 * O mês, dia a dia.
 *
 * ## Por que barras de LUCRO, e não três linhas
 *
 * Receita, custo e lucro são a mesma conta — lucro é receita menos custo. Três
 * linhas fazem o leitor conferir a subtração no olho; uma barra de lucro
 * responde direto a pergunta que traz alguém aqui ("estou acima da água?"), e os
 * outros dois números aparecem no hover e na tabela, sem sumir.
 *
 * Dinheiro por dia é discreto: um dia sem pagamento é um zero de verdade, não um
 * ponto de uma curva contínua. Barra representa isso; linha sugeriria um fluxo
 * que não existe.
 *
 * ## O sinal não é só cor
 *
 * Verde e vermelho ficam a ΔE 6,5 em deuteranopia — medido, não estimado. Quem
 * enxerga assim não distinguiria lucro de prejuízo pelo matiz. Então o sinal é
 * codificado três vezes: pela DIREÇÃO da barra em relação à linha do zero, pelo
 * `+`/`−` no valor, e só então pela cor.
 *
 * A tabela abaixo do gráfico existe pelo mesmo motivo, mais impressão e leitor
 * de tela: nenhum número aqui vive só no hover.
 */

const L = 44; // margem esquerda, para os rótulos de valor
const R = 8;
const T = 12;
const B = 22;
const W = 760;
const H = 200;

function formatarDia(iso: string): string {
  return iso.slice(8, 10);
}

/** Barra com as pontas de fora arredondadas e a base encostada no zero. */
function caminhoBarra(x: number, y: number, largura: number, altura: number, cima: boolean) {
  const r = Math.min(3, largura / 2, Math.abs(altura));
  if (altura <= 0.5) return "";
  return cima
    ? `M${x},${y + altura} L${x},${y + r} Q${x},${y} ${x + r},${y} L${x + largura - r},${y} Q${x + largura},${y} ${x + largura},${y + r} L${x + largura},${y + altura} Z`
    : `M${x},${y} L${x},${y + altura - r} Q${x},${y + altura} ${x + r},${y + altura} L${x + largura - r},${y + altura} Q${x + largura},${y + altura} ${x + largura},${y + altura - r} L${x + largura},${y} Z`;
}

export default function AdminSeriesChart({ serie }: { serie: SerieDia[] }) {
  const [ativo, setAtivo] = useState<SerieDia | null>(null);

  if (serie.length === 0) return null;

  const lucros = serie.map((d) => Number(d.lucro_brl));
  const maior = Math.max(0, ...lucros);
  const menor = Math.min(0, ...lucros);
  const amplitude = maior - menor || 1;

  const larguraUtil = W - L - R;
  const alturaUtil = H - T - B;
  const passo = larguraUtil / serie.length;
  const larguraBarra = Math.max(4, passo * 0.62);
  const zeroY = T + (maior / amplitude) * alturaUtil;

  const temMovimento = lucros.some((v) => v !== 0);

  return (
    <section className="flex flex-col gap-2">
      <div className="flex flex-wrap items-baseline gap-x-3">
        <h2 className="text-body font-medium text-ink">Lucro por dia</h2>
        <span className="text-label text-ink-muted">
          receita menos custo variável · fuso de São Paulo
        </span>
      </div>

      <div className="relative overflow-x-auto rounded-md border border-line bg-raised p-3">
        <svg
          viewBox={`0 0 ${W} ${H}`}
          className="block h-[200px] w-full min-w-[38rem]"
          role="img"
          aria-label="Lucro por dia do mês"
        >
          {/* Grade recessiva: só a linha do zero e os dois extremos. */}
          <line
            x1={L}
            x2={W - R}
            y1={zeroY}
            y2={zeroY}
            stroke="var(--color-line-strong)"
            strokeWidth="1"
          />
          <text
            x={L - 6}
            y={zeroY + 3}
            textAnchor="end"
            className="fill-[var(--color-ink-muted)] text-[9px]"
          >
            0
          </text>
          {maior > 0 && (
            <text
              x={L - 6}
              y={T + 8}
              textAnchor="end"
              className="fill-[var(--color-ink-muted)] text-[9px]"
            >
              {formatarBRL(maior)}
            </text>
          )}
          {menor < 0 && (
            <text
              x={L - 6}
              y={H - B}
              textAnchor="end"
              className="fill-[var(--color-ink-muted)] text-[9px]"
            >
              {formatarBRL(menor)}
            </text>
          )}

          {serie.map((dia, i) => {
            const valor = Number(dia.lucro_brl);
            const x = L + i * passo + (passo - larguraBarra) / 2;
            const altura = (Math.abs(valor) / amplitude) * alturaUtil;
            const positivo = valor >= 0;
            const y = positivo ? zeroY - altura : zeroY;
            const destacado = ativo?.dia === dia.dia;

            return (
              <g
                key={dia.dia}
                onMouseEnter={() => setAtivo(dia)}
                onMouseLeave={() => setAtivo(null)}
              >
                {/* Alvo de hover maior que a marca: uma barra de 2px de altura
                    seria impossível de acertar com o mouse. */}
                <rect
                  x={L + i * passo}
                  y={T}
                  width={passo}
                  height={alturaUtil}
                  fill={destacado ? "var(--color-hover)" : "transparent"}
                />
                <path
                  d={caminhoBarra(x, y, larguraBarra, altura, positivo)}
                  fill={positivo ? "var(--color-mint)" : "var(--color-danger)"}
                  opacity={ativo && !destacado ? 0.45 : 1}
                />
                {i % 5 === 0 && (
                  <text
                    x={L + i * passo + passo / 2}
                    y={H - 6}
                    textAnchor="middle"
                    className="fill-[var(--color-ink-muted)] text-[9px]"
                  >
                    {formatarDia(dia.dia)}
                  </text>
                )}
              </g>
            );
          })}
        </svg>

        {!temMovimento && (
          <p className="pt-1 text-label text-ink-muted">
            Nenhum movimento neste mês ainda.
          </p>
        )}

        {ativo && (
          <div className="pointer-events-none absolute right-3 top-3 rounded-sm border border-line-strong bg-inset px-3 py-2 text-label">
            <p className="text-ink">{ativo.dia}</p>
            <p className="tabular text-ink-dim">
              receita {formatarBRL(ativo.receita_brl)}
            </p>
            <p className="tabular text-ink-dim">
              custo {formatarBRL(ativo.custo_brl)}
            </p>
            <p
              className={`tabular font-medium ${
                Number(ativo.lucro_brl) >= 0 ? "text-mint" : "text-danger"
              }`}
            >
              lucro {Number(ativo.lucro_brl) >= 0 ? "+" : "−"}
              {formatarBRL(Math.abs(Number(ativo.lucro_brl)))}
            </p>
          </div>
        )}
      </div>

      {/* Nenhum número vive só no hover. */}
      <details className="rounded-md border border-line bg-raised">
        <summary className="cursor-pointer px-4 py-2 text-label text-ink-dim hover:text-ink">
          Ver os números do mês
        </summary>
        <div className="overflow-x-auto border-t border-line">
          <table className="w-full min-w-[26rem] text-body">
            <thead>
              <tr className="border-b border-line text-label text-ink-muted">
                <th className="px-4 py-2 text-left font-normal">Dia</th>
                <th className="px-4 py-2 text-right font-normal">Receita</th>
                <th className="px-4 py-2 text-right font-normal">Custo</th>
                <th className="px-4 py-2 text-right font-normal">Lucro</th>
              </tr>
            </thead>
            <tbody>
              {serie
                .filter(
                  (d) =>
                    Number(d.receita_brl) !== 0 || Number(d.custo_brl) !== 0,
                )
                .map((d) => (
                  <tr key={d.dia} className="border-b border-line last:border-0">
                    <td className="tabular px-4 py-1.5 text-ink-dim">{d.dia}</td>
                    <td className="tabular px-4 py-1.5 text-right text-ink">
                      {formatarBRL(d.receita_brl)}
                    </td>
                    <td className="tabular px-4 py-1.5 text-right text-ink">
                      {formatarBRL(d.custo_brl)}
                    </td>
                    <td
                      className={`tabular px-4 py-1.5 text-right font-medium ${
                        Number(d.lucro_brl) >= 0 ? "text-mint" : "text-danger"
                      }`}
                    >
                      {Number(d.lucro_brl) >= 0 ? "+" : "−"}
                      {formatarBRL(Math.abs(Number(d.lucro_brl)))}
                    </td>
                  </tr>
                ))}
            </tbody>
          </table>
        </div>
      </details>
    </section>
  );
}
