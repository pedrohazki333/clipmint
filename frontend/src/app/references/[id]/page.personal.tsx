"use client";

import { useEffect, useRef, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import Link from "next/link";
import type { Performance, Reference } from "@/lib/types";
import { getApiErrorMessage } from "@/lib/api";
import {
  confirmReference,
  deleteReference,
  getReference,
  updateReference,
} from "@/personal/learning-api";
import ReferenceStatus from "@/components/ReferenceStatus";
import ClipForensicsPanel from "@/components/ClipForensicsPanel";

const POLLING_INTERVAL = 3000;
const TERMINAL = new Set(["done", "error"]);

const PERFORMANCE_OPTS: { value: Performance; label: string }[] = [
  { value: "viral", label: "Viralizou" },
  { value: "muito_bom", label: "Muito bom" },
  { value: "bom", label: "Bom" },
];

function fmtTime(s: number | null): string {
  if (s == null) return "—";
  const total = Math.floor(s);
  const m = Math.floor(total / 60);
  const sec = total % 60;
  return `${m}:${String(sec).padStart(2, "0")}`;
}

function confidenceStyle(c: number): { label: string; cls: string } {
  if (c >= 0.85) return { label: "Alta", cls: "text-mint" };
  if (c >= 0.6) return { label: "Média", cls: "text-running" };
  return { label: "Baixa", cls: "text-danger" };
}

export default function ReferencePage() {
  const { id } = useParams<{ id: string }>();
  const router = useRouter();
  const [ref, setRef] = useState<Reference | null>(null);
  const [error, setError] = useState("");
  const intervalRef = useRef<ReturnType<typeof setInterval> | null>(null);

  // Estado editável
  const [startStr, setStartStr] = useState("");
  const [endStr, setEndStr] = useState("");
  const [performance, setPerformance] = useState<Performance>("viral");
  const [views, setViews] = useState("");
  const [notas, setNotas] = useState("");

  const [reanalyzing, setReanalyzing] = useState(false);
  const [confirming, setConfirming] = useState(false);
  const [actionError, setActionError] = useState("");

  // Preenche o formulário quando a análise fica pronta (uma vez)
  const hydratedRef = useRef(false);
  function hydrate(r: Reference) {
    if (hydratedRef.current) return;
    if (r.status === "done") {
      setStartStr(r.source_start != null ? String(r.source_start) : "");
      setEndStr(r.source_end != null ? String(r.source_end) : "");
      if (r.performance) setPerformance(r.performance);
      if (r.views != null) setViews(String(r.views));
      if (r.notas) setNotas(r.notas);
      hydratedRef.current = true;
    }
  }

  async function fetchRef() {
    try {
      const data = await getReference(id);
      setRef(data);
      setError("");
      hydrate(data);
      if (TERMINAL.has(data.status) && intervalRef.current) {
        clearInterval(intervalRef.current);
        intervalRef.current = null;
      }
    } catch {
      setError("Não foi possível carregar a referência.");
    }
  }

  useEffect(() => {
    fetchRef();
    intervalRef.current = setInterval(fetchRef, POLLING_INTERVAL);
    return () => {
      if (intervalRef.current) clearInterval(intervalRef.current);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [id]);

  async function handleReanalyze() {
    setActionError("");
    const start = parseFloat(startStr);
    const end = parseFloat(endStr);
    if (isNaN(start) || isNaN(end) || end <= start) {
      setActionError("Intervalo inválido: o fim deve ser maior que o início.");
      return;
    }
    setReanalyzing(true);
    try {
      const updated = await updateReference(id, {
        source_start: start,
        source_end: end,
        reanalyze: true,
      });
      setRef(updated);
    } catch (err) {
      setActionError(getApiErrorMessage(err, "Não foi possível reanalisar."));
    } finally {
      setReanalyzing(false);
    }
  }

  async function handleConfirm() {
    setActionError("");
    setConfirming(true);
    try {
      // Grava performance/views/notas antes de publicar
      await updateReference(id, {
        performance,
        views: views.trim() ? parseInt(views, 10) : undefined,
        notas: notas.trim() || undefined,
      });
      await confirmReference(id);
      await fetchRef();
    } catch (err) {
      setActionError(getApiErrorMessage(err, "Não foi possível confirmar."));
    } finally {
      setConfirming(false);
    }
  }

  async function handleDelete() {
    if (!confirm("Excluir esta referência e seus arquivos?")) return;
    try {
      await deleteReference(id);
      router.push("/");
    } catch (err) {
      setActionError(getApiErrorMessage(err, "Não foi possível excluir."));
    }
  }

  if (error) {
    return (
      <div className="rounded-md bg-danger-soft border border-danger/40 p-6 text-danger">{error}</div>
    );
  }
  if (!ref) {
    return <div className="text-center py-20 text-ink-dim animate-pulse">Carregando...</div>;
  }

  const a = ref.analysis;
  const isStandalone = ref.kind === "standalone";
  const conf = ref.alignment_confidence != null ? confidenceStyle(ref.alignment_confidence) : null;

  return (
    <div className="flex flex-col gap-6">
      <Link href="/" className="text-body text-ink-dim hover:text-ink transition-colors">
        ← Voltar
      </Link>

      {/* Header */}
      <div className="rounded-md bg-raised border border-line p-6 flex flex-col gap-4">
        <div>
          <h1 className="text-title font-bold text-ink leading-tight">
            {ref.source_title || "Processando referência..."}
          </h1>
          <p className="text-body text-ink-dim mt-1">
            {[
              ref.source_channel,
              isStandalone ? "clipe sem vídeo de origem" : "clipe + vídeo original",
              ref.source_type,
            ]
              .filter(Boolean)
              .join(" · ")}
          </p>
          {ref.source_url && (
            <a
              href={ref.source_url}
              target="_blank"
              rel="noreferrer"
              className="text-label text-ink-muted hover:text-ink-dim break-all"
            >
              {ref.source_url}
            </a>
          )}
        </div>
        <div className="pt-1">
          <ReferenceStatus
            status={ref.status}
            kind={ref.kind}
            errorMessage={ref.error_message}
          />
        </div>
      </div>

      {ref.published && (
        <div className="rounded-md bg-mint-soft border border-mint/30 px-4 py-3 text-body text-mint">
          ✓ Referência confirmada e adicionada ao aprendizado do ClipMint. Ela agora calibra as
          próximas análises.
        </div>
      )}

      {ref.status === "done" && (
        <>
          {/* Sem vídeo de origem não há intervalo a ajustar: o clipe já é o corte. */}
          {isStandalone && (
            <div className="rounded-md bg-raised border border-line p-6 flex flex-wrap items-baseline gap-x-6 gap-y-2">
              <div>
                <p className="text-label text-ink-dim mb-1">Duração</p>
                <p className="text-body text-ink">
                  {ref.clip_duration != null ? `${ref.clip_duration.toFixed(1)}s` : "—"}
                </p>
              </div>
              {ref.opening_phrase && (
                <div className="min-w-0">
                  <p className="text-label text-ink-dim mb-1">Frase de abertura</p>
                  <p className="text-body text-ink italic">“{ref.opening_phrase}”</p>
                </div>
              )}
            </div>
          )}

          {/* Corte localizado */}
          {!isStandalone && (
          <div className="rounded-md bg-raised border border-line p-6 flex flex-col gap-4">
            <div className="flex items-center justify-between">
              <h2 className="text-body font-semibold text-ink">Corte localizado no original</h2>
              {conf && (
                <span className="text-label text-ink-dim">
                  Confiança do alinhamento:{" "}
                  <span className={`font-semibold ${conf.cls}`}>
                    {Math.round((ref.alignment_confidence ?? 0) * 100)}% ({conf.label})
                  </span>
                </span>
              )}
            </div>

            {ref.alignment_confidence != null && ref.alignment_confidence < 0.6 && (
              <p className="text-label text-amber-500/90 bg-amber-900/15 rounded px-3 py-2">
                Confiança baixa — confira o intervalo abaixo e ajuste se necessário antes de confirmar.
              </p>
            )}

            <div className="flex flex-wrap items-end gap-4">
              <div className="flex flex-col gap-1">
                <label className="text-label text-ink-dim">Início (s)</label>
                <input
                  type="number"
                  step="0.1"
                  value={startStr}
                  onChange={(e) => setStartStr(e.target.value)}
                  className="w-28 rounded-sm bg-inset border border-line px-3 py-2 text-ink focus:outline-none focus:border-mint"
                />
              </div>
              <div className="flex flex-col gap-1">
                <label className="text-label text-ink-dim">Fim (s)</label>
                <input
                  type="number"
                  step="0.1"
                  value={endStr}
                  onChange={(e) => setEndStr(e.target.value)}
                  className="w-28 rounded-sm bg-inset border border-line px-3 py-2 text-ink focus:outline-none focus:border-mint"
                />
              </div>
              <div className="text-body text-ink-dim pb-2">
                {fmtTime(parseFloat(startStr) || 0)} → {fmtTime(parseFloat(endStr) || 0)}
                {" · "}
                {Math.max(0, (parseFloat(endStr) || 0) - (parseFloat(startStr) || 0)).toFixed(0)}s
              </div>
              <button
                onClick={handleReanalyze}
                disabled={reanalyzing || ref.published}
                className="ml-auto rounded-sm bg-inset hover:bg-hover border border-line px-4 py-2 text-body text-ink transition-colors disabled:opacity-50"
              >
                {reanalyzing ? "Reanalisando..." : "Ajustar e reanalisar"}
              </button>
            </div>

            {ref.opening_phrase && (
              <div>
                <p className="text-label text-ink-dim mb-1">Frase de abertura</p>
                <p className="text-body text-ink italic">“{ref.opening_phrase}”</p>
              </div>
            )}
          </div>
          )}

          {/* Análise da IA */}
          {a && (
            <div className="rounded-md bg-raised border border-line p-6 flex flex-col gap-4">
              <div className="flex items-center justify-between">
                <h2 className="text-body font-semibold text-ink">
                  {isStandalone ? "Por que este clipe funciona" : "Por que este corte funciona"}
                </h2>
                <span className="rounded-full bg-mint-soft border border-mint/30 px-3 py-1 text-body font-semibold text-mint">
                  {a.virality_score.toFixed(1)}
                </span>
              </div>

              {a.hook && (
                <div>
                  <p className="text-label text-ink-dim mb-1">Hook sugerido</p>
                  <p className="text-title font-bold text-ink">{a.hook}</p>
                </div>
              )}
              {a.suggested_title && (
                <div>
                  <p className="text-label text-ink-dim mb-1">Título sugerido</p>
                  <p className="text-body text-ink">{a.suggested_title}</p>
                </div>
              )}
              {a.reason && (
                <div>
                  <p className="text-label text-ink-dim mb-1">Análise</p>
                  <p className="text-body text-ink leading-relaxed">{a.reason}</p>
                </div>
              )}
              {a.why_this_cut && (
                <div>
                  <p className="text-label text-ink-dim mb-1">
                    {isStandalone
                      ? "Onde ele começa e termina"
                      : "Por que começa e termina onde termina"}
                  </p>
                  <p className="text-body text-ink leading-relaxed">{a.why_this_cut}</p>
                </div>
              )}
              {a.tags?.length > 0 && (
                <div className="flex flex-wrap gap-2">
                  {a.tags.map((t) => (
                    <span
                      key={t}
                      className="rounded-full bg-inset border border-line px-3 py-1 text-label text-ink-dim"
                    >
                      {t}
                    </span>
                  ))}
                </div>
              )}
            </div>
          )}

          {/* Perícia — só existe no modo standalone */}
          {ref.forensics && <ClipForensicsPanel forensics={ref.forensics} />}

          {/* Confirmar e ensinar */}
          {!ref.published && (
            <div className="rounded-md bg-raised border border-line p-6 flex flex-col gap-4">
              <h2 className="text-body font-semibold text-ink">Confirmar e ensinar</h2>
              <p className="text-body text-ink-dim -mt-2">
                Ajuste a performance real e adicione o que você aprendeu. Ao confirmar, esta
                referência entra no aprendizado das próximas análises.
              </p>

              <div className="flex flex-col gap-2">
                <label className="text-label text-ink-dim">Performance</label>
                <div className="flex gap-2">
                  {PERFORMANCE_OPTS.map((opt) => (
                    <button
                      key={opt.value}
                      onClick={() => setPerformance(opt.value)}
                      className={`rounded-sm px-4 py-2 text-body font-medium border transition-colors ${
                        performance === opt.value
                          ? "bg-mint-strong border-mint text-white"
                          : "bg-inset border-line text-ink hover:bg-hover"
                      }`}
                    >
                      {opt.label}
                    </button>
                  ))}
                </div>
              </div>

              <div className="flex flex-col gap-2">
                <label className="text-label text-ink-dim">Views reais (opcional)</label>
                <input
                  type="number"
                  value={views}
                  onChange={(e) => setViews(e.target.value)}
                  placeholder="ex: 250000"
                  className="w-48 rounded-sm bg-inset border border-line px-3 py-2 text-ink placeholder-ink-muted focus:outline-none focus:border-mint"
                />
              </div>

              <div className="flex flex-col gap-2">
                <label className="text-label text-ink-dim">
                  O que você aprendeu (opcional — vira a explicação usada no aprendizado)
                </label>
                <textarea
                  value={notas}
                  onChange={(e) => setNotas(e.target.value)}
                  rows={3}
                  placeholder="Ex: o hook nos primeiros 2s + a revelação no meio seguraram até o fim."
                  className="w-full rounded-sm bg-inset border border-line px-3 py-2 text-ink placeholder-ink-muted focus:outline-none focus:border-mint resize-y"
                />
              </div>

              {actionError && (
                <p className="text-body text-danger bg-danger-soft rounded px-3 py-2">{actionError}</p>
              )}

              <div className="flex items-center gap-3">
                <button
                  onClick={handleConfirm}
                  disabled={confirming}
                  className="rounded-sm bg-mint-strong hover:bg-mint disabled:bg-inset px-6 py-3 font-semibold text-white transition-colors"
                >
                  {confirming ? "Confirmando..." : "Confirmar e ensinar"}
                </button>
                <button
                  onClick={handleDelete}
                  className="text-label text-ink-dim hover:text-red-400 transition-colors"
                >
                  Excluir referência
                </button>
              </div>
            </div>
          )}
        </>
      )}

      {ref.status === "error" && (
        <button
          onClick={handleDelete}
          className="self-start text-label text-ink-dim hover:text-red-400 transition-colors"
        >
          Excluir referência
        </button>
      )}

      {actionError && ref.published && (
        <p className="text-body text-danger bg-danger-soft rounded px-3 py-2">{actionError}</p>
      )}
    </div>
  );
}
