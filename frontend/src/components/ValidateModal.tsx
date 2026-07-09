"use client";

import { useEffect, useRef, useState } from "react";
import { validateClip } from "@/lib/api";

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
      <div className="w-full max-w-md rounded-2xl bg-gray-900 border border-gray-700 p-6 flex flex-col gap-5 shadow-2xl">
        {/* Header */}
        <div className="flex items-center justify-between">
          <h2 className="text-base font-semibold text-gray-100">
            Salvar como exemplo validado
          </h2>
          <button
            onClick={onClose}
            className="text-gray-500 hover:text-gray-300 transition-colors text-lg leading-none"
          >
            ✕
          </button>
        </div>

        {saved ? (
          /* Estado de sucesso */
          <div className="flex flex-col items-center gap-3 py-4 text-center">
            <div className="text-3xl">✓</div>
            <p className="text-emerald-400 font-medium">Exemplo salvo com sucesso!</p>
            <p className="text-xs text-gray-500">
              Este clip será usado como referência nas próximas análises.
            </p>
            <button
              onClick={onClose}
              className="mt-2 px-5 py-2 rounded-lg bg-gray-800 hover:bg-gray-700 text-sm text-gray-300 transition-colors"
            >
              Fechar
            </button>
          </div>
        ) : (
          <>
            {/* Performance */}
            <div className="flex flex-col gap-1.5">
              <label className="text-xs font-medium text-gray-400 uppercase tracking-wide">
                Performance
              </label>
              <div className="flex gap-2">
                {PERFORMANCE_OPTIONS.map((opt) => (
                  <button
                    key={opt.value}
                    onClick={() => setPerformance(opt.value)}
                    className={`flex-1 rounded-lg py-2 text-sm font-medium border transition-colors ${
                      performance === opt.value
                        ? "bg-emerald-600 border-emerald-500 text-white"
                        : "bg-gray-800 border-gray-700 text-gray-400 hover:border-gray-500"
                    }`}
                  >
                    {opt.label}
                  </button>
                ))}
              </div>
            </div>

            {/* Aprendizado */}
            <div className="flex flex-col gap-1.5">
              <label className="text-xs font-medium text-gray-400 uppercase tracking-wide">
                Por que esse clip funcionou?
              </label>
              <textarea
                value={aprendizado}
                onChange={(e) => setAprendizado(e.target.value)}
                placeholder="Ex: Hook de revelação no início + tensão crescente. Público sentiu que estava aprendendo um segredo."
                rows={3}
                className="rounded-lg bg-gray-800 border border-gray-700 text-sm text-gray-200 placeholder-gray-600 px-3 py-2 resize-none focus:outline-none focus:border-gray-500 transition-colors"
              />
            </div>

            {/* Views */}
            <div className="flex flex-col gap-1.5">
              <label className="text-xs font-medium text-gray-400 uppercase tracking-wide">
                Views obtidos{" "}
                <span className="normal-case font-normal text-gray-600">(opcional)</span>
              </label>
              <input
                type="number"
                min={0}
                value={views}
                onChange={(e) => setViews(e.target.value)}
                placeholder="Ex: 50000"
                className="rounded-lg bg-gray-800 border border-gray-700 text-sm text-gray-200 placeholder-gray-600 px-3 py-2 focus:outline-none focus:border-gray-500 transition-colors"
              />
            </div>

            {/* Erro */}
            {error && (
              <p className="text-xs text-red-400 bg-red-900/20 rounded px-3 py-2">
                {error}
              </p>
            )}

            {/* Ações */}
            <div className="flex gap-2 pt-1">
              <button
                onClick={onClose}
                className="flex-1 rounded-lg py-2 text-sm text-gray-400 bg-gray-800 hover:bg-gray-700 border border-gray-700 transition-colors"
              >
                Cancelar
              </button>
              <button
                onClick={handleConfirm}
                disabled={saving}
                className="flex-1 rounded-lg py-2 text-sm font-semibold text-white bg-emerald-600 hover:bg-emerald-500 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
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
