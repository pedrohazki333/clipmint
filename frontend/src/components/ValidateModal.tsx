"use client";

import { useEffect, useRef, useState } from "react";
import { validateClip } from "@/personal/learning-api";

type Performance = "viral" | "muito_bom" | "bom";

interface Props {
  clipId: string;
  onClose: () => void;
}

const PERFORMANCE_OPTIONS: { value: Performance; label: string }[] = [
  { value: "viral", label: "Viral" },
  { value: "muito_bom", label: "Muito bom" },
  { value: "bom", label: "Bom" },
];

export default function ValidateModal({ clipId, onClose }: Props) {
  const [performance, setPerformance] = useState<Performance>("viral");
  const [aprendizado, setAprendizado] = useState("");
  const [views, setViews] = useState("");
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const [error, setError] = useState("");
  const backdropRef = useRef<HTMLDivElement>(null);

  // Fecha com Escape
  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") onClose();
    }
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [onClose]);

  // Fecha ao clicar fora do card
  function handleBackdropClick(e: React.MouseEvent<HTMLDivElement>) {
    if (e.target === backdropRef.current) onClose();
  }

  async function handleConfirm() {
    setSaving(true);
    setError("");
    try {
      await validateClip(clipId, {
        performance,
        aprendizado,
        views: views ? Number(views) : undefined,
      });
      setSaved(true);
    } catch {
      setError("Não foi possível salvar o exemplo. Tente novamente.");
    } finally {
      setSaving(false);
    }
  }

  return (
    <div
      ref={backdropRef}
      onClick={handleBackdropClick}
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm px-4"
    >
      <div className="w-full max-w-md rounded-md bg-raised border border-line p-6 flex flex-col gap-5 shadow-2xl">
        {/* Header */}
        <div className="flex items-center justify-between">
          <h2 className="text-body font-semibold text-ink">
            Salvar como exemplo validado
          </h2>
          <button
            onClick={onClose}
            className="text-ink-dim hover:text-ink transition-colors text-title leading-none"
          >
            ✕
          </button>
        </div>

        {saved ? (
          /* Estado de sucesso */
          <div className="flex flex-col items-center gap-3 py-4 text-center">
            <div className="text-display">✓</div>
            <p className="text-mint font-medium">Exemplo salvo com sucesso!</p>
            <p className="text-label text-ink-dim">
              Este clip será usado como referência nas próximas análises.
            </p>
            <button
              onClick={onClose}
              className="mt-2 px-5 py-2 rounded-sm bg-inset hover:bg-hover text-body text-ink transition-colors"
            >
              Fechar
            </button>
          </div>
        ) : (
          <>
            {/* Performance */}
            <div className="flex flex-col gap-1.5">
              <label className="text-label font-medium text-ink-dim uppercase tracking-wide">
                Performance
              </label>
              <div className="flex gap-2">
                {PERFORMANCE_OPTIONS.map((opt) => (
                  <button
                    key={opt.value}
                    onClick={() => setPerformance(opt.value)}
                    className={`flex-1 rounded-sm py-2 text-body font-medium border transition-colors ${
                      performance === opt.value
                        ? "bg-mint-strong border-mint text-white"
                        : "bg-inset border-line text-ink-dim hover:border-line-strong"
                    }`}
                  >
                    {opt.label}
                  </button>
                ))}
              </div>
            </div>

            {/* Aprendizado */}
            <div className="flex flex-col gap-1.5">
              <label className="text-label font-medium text-ink-dim uppercase tracking-wide">
                Por que esse clip funcionou?
              </label>
              <textarea
                value={aprendizado}
                onChange={(e) => setAprendizado(e.target.value)}
                placeholder="Ex: Hook de revelação no início + tensão crescente. Público sentiu que estava aprendendo um segredo."
                rows={3}
                className="rounded-sm bg-inset border border-line text-body text-ink placeholder-ink-muted px-3 py-2 resize-none focus:outline-none focus:border-mint transition-colors"
              />
            </div>

            {/* Views */}
            <div className="flex flex-col gap-1.5">
              <label className="text-label font-medium text-ink-dim uppercase tracking-wide">
                Views obtidos{" "}
                <span className="normal-case font-normal text-ink-muted">(opcional)</span>
              </label>
              <input
                type="number"
                min={0}
                value={views}
                onChange={(e) => setViews(e.target.value)}
                placeholder="Ex: 50000"
                className="rounded-sm bg-inset border border-line text-body text-ink placeholder-ink-muted px-3 py-2 focus:outline-none focus:border-mint transition-colors"
              />
            </div>

            {/* Erro */}
            {error && (
              <p className="text-label text-danger bg-danger-soft rounded px-3 py-2">
                {error}
              </p>
            )}

            {/* Ações */}
            <div className="flex gap-2 pt-1">
              <button
                onClick={onClose}
                className="flex-1 rounded-sm py-2 text-body text-ink-dim bg-inset hover:bg-hover border border-line transition-colors"
              >
                Cancelar
              </button>
              <button
                onClick={handleConfirm}
                disabled={saving}
                className="flex-1 rounded-sm py-2 text-body font-semibold text-white bg-mint-strong hover:bg-mint disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
              >
                {saving ? "Salvando..." : "Confirmar"}
              </button>
            </div>
          </>
        )}
      </div>
    </div>
  );
}
