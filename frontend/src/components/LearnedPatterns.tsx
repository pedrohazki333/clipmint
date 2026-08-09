"use client";

import { useEffect, useState } from "react";
import type { LearnedPatterns as Patterns } from "@/lib/types";
import { deletePatterns, getApiErrorMessage, getPatterns, minePatterns } from "@/lib/api";

function fmtDate(iso: string | null): string {
  if (!iso) return "";
  try {
    return new Date(iso).toLocaleString("pt-BR", { dateStyle: "short", timeStyle: "short" });
  } catch {
    return "";
  }
}

export default function LearnedPatterns() {
  const [data, setData] = useState<Patterns | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  async function load() {
    try {
      setData(await getPatterns());
    } catch {
      // silencioso — painel secundário
    }
  }

  useEffect(() => {
    load();
  }, []);

  async function handleMine() {
    setBusy(true);
    setError("");
    try {
      setData(await minePatterns());
    } catch (err) {
      setError(getApiErrorMessage(err, "Não foi possível minerar padrões."));
    } finally {
      setBusy(false);
    }
  }

  async function handleClear() {
    if (!confirm("Remover os padrões aprendidos?")) return;
    setBusy(true);
    setError("");
    try {
      await deletePatterns();
      await load();
    } catch (err) {
      setError(getApiErrorMessage(err, "Não foi possível remover."));
    } finally {
      setBusy(false);
    }
  }

  const hasPatterns = data && data.patterns.length > 0;
  const available = data?.available_examples ?? 0;
  const canMine = available > 0;

  return (
    <div className="rounded-2xl bg-gray-900 border border-gray-800 p-6">
      <div className="flex items-start justify-between gap-4">
        <div>
          <h2 className="text-base font-semibold text-gray-100">Padrões aprendidos</h2>
          <p className="text-sm text-gray-500 mt-1">
            Heurísticas destiladas do conjunto de exemplos validados. Uma vez calculadas, guiam
            todas as próximas análises de viralidade.
          </p>
        </div>
        <button
          onClick={handleMine}
          disabled={busy || !canMine}
          title={!canMine ? "Confirme ao menos uma referência ou clipe primeiro" : ""}
          className="flex-shrink-0 rounded-lg bg-gray-800 hover:bg-gray-700 border border-gray-700 px-4 py-2 text-sm text-gray-200 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
        >
          {busy ? "Processando..." : hasPatterns ? "Recalcular" : "Minerar padrões"}
        </button>
      </div>

      {!canMine && !hasPatterns && (
        <p className="mt-4 text-xs text-gray-600 bg-gray-800/40 rounded px-3 py-2">
          Ainda não há exemplos validados. Confirme uma referência (ou valide um clipe) para poder
          minerar padrões.
        </p>
      )}

      {hasPatterns && (
        <>
          <ul className="mt-4 flex flex-col gap-2">
            {data!.patterns.map((p, i) => (
              <li key={i} className="flex gap-2 text-sm text-gray-300 leading-relaxed">
                <span className="text-emerald-500 flex-shrink-0">▹</span>
                <span>{p}</span>
              </li>
            ))}
          </ul>

          <div className="mt-4 flex items-center justify-between gap-4">
            <p className="text-xs text-gray-600">
              De {data!.n_examples} exemplo{data!.n_examples !== 1 ? "s" : ""}
              {data!.generated_at && ` · ${fmtDate(data!.generated_at)}`}
            </p>
            <button
              onClick={handleClear}
              disabled={busy}
              className="text-xs text-gray-600 hover:text-red-400 transition-colors disabled:opacity-50"
            >
              Remover
            </button>
          </div>

          {data!.stale && (
            <p className="mt-3 text-xs text-amber-500/90 bg-amber-900/15 rounded px-3 py-2">
              Há {available} exemplo{available !== 1 ? "s" : ""} validado
              {available !== 1 ? "s" : ""} agora ({data!.n_examples} usado
              {data!.n_examples !== 1 ? "s" : ""} no cálculo atual). Recalcule para incorporar os
              novos.
            </p>
          )}
        </>
      )}

      {error && (
        <p className="mt-3 text-xs text-red-400 bg-red-900/20 rounded px-3 py-2">{error}</p>
      )}
    </div>
  );
}
