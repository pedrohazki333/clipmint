"use client";

import { useEffect, useRef } from "react";

/**
 * A barra de andamento do job — uma só, no rodapé do bloco de status.
 *
 * ── Como ela anda ───────────────────────────────────────────────────────────
 * O servidor manda dois números (ver backend/app/services/progress.py): `pct`,
 * o que já aconteceu de verdade, e `ate`, onde o passo atual termina. A barra
 * salta para o `pct` quando um evento real chega — bytes baixados, áudio
 * enviado, clipe pronto — e, entre um evento e outro, desliza devagar rumo ao
 * `ate` sem nunca alcançá-lo.
 *
 * O deslize é exponencial: cobre 63% do que falta em ~25 segundos, depois cada
 * vez menos. Isso dá o comportamento que se espera de uma barra honesta —
 * rápida quando acabou de acontecer alguma coisa, cada vez mais lenta quando a
 * espera se estende — e garante que ela nunca ultrapasse o fim do passo.
 *
 * ── Por que fora do React ───────────────────────────────────────────────────
 * O valor muda a 60 quadros por segundo. Passar isso por `useState` seria
 * sessenta renders por segundo numa página que também faz polling e desenha
 * uma dúzia de cartões com vídeo. A largura é escrita direto no nó, que é para
 * isso que `ref` existe.
 *
 * Nunca anda para trás: um relato que chegue fora de ordem é ignorado se for
 * menor que a posição atual.
 */

/** Segundos para o deslize cobrir 63% do que falta até o teto. */
const CONSTANTE_DE_TEMPO = 25;

export default function ProgressBar({
  pct,
  ate,
  /** Job terminado: a barra trava cheia, sem deslize. */
  completo = false,
}: {
  pct: number;
  ate: number;
  completo?: boolean;
}) {
  const trilho = useRef<HTMLDivElement>(null);
  const rotulo = useRef<HTMLSpanElement>(null);
  const estado = useRef({ valor: pct, ate });

  // O alvo vem do servidor; a posição atual nunca recua.
  useEffect(() => {
    estado.current.valor = Math.max(estado.current.valor, pct);
    estado.current.ate = Math.max(ate, pct);
  }, [pct, ate]);

  useEffect(() => {
    if (completo) {
      estado.current.valor = 100;
      if (trilho.current) trilho.current.style.width = "100%";
      if (rotulo.current) rotulo.current.textContent = "100%";
      return;
    }

    const quieto = window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;
    let anterior = performance.now();
    let quadro = 0;

    const passo = (agora: number) => {
      const dt = Math.min((agora - anterior) / 1000, 0.5);
      anterior = agora;
      const st = estado.current;

      // Quem pediu menos movimento recebe o valor real, sem o deslize: a barra
      // ainda anda, só que aos saltos dos eventos.
      if (!quieto && st.valor < st.ate) {
        st.valor += (st.ate - st.valor) * (1 - Math.exp(-dt / CONSTANTE_DE_TEMPO));
      }

      if (trilho.current) trilho.current.style.width = `${st.valor.toFixed(2)}%`;
      if (rotulo.current) rotulo.current.textContent = `${Math.floor(st.valor)}%`;
      quadro = requestAnimationFrame(passo);
    };

    quadro = requestAnimationFrame(passo);
    return () => cancelAnimationFrame(quadro);
  }, [completo]);

  return (
    <div className="flex items-center gap-3">
      <div
        className="h-1.5 flex-1 overflow-hidden rounded-full bg-line"
        role="progressbar"
        aria-valuenow={Math.floor(pct)}
        aria-valuemin={0}
        aria-valuemax={100}
        aria-label="Andamento do processamento"
      >
        <div
          ref={trilho}
          className="h-full rounded-full bg-mint"
          style={{ width: `${pct}%` }}
        />
      </div>
      <span
        ref={rotulo}
        className="tabular w-9 flex-shrink-0 text-right text-label text-ink-dim"
      >
        {Math.floor(pct)}%
      </span>
    </div>
  );
}
