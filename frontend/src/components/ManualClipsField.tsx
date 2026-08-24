"use client";

import type { ManualMode } from "@/lib/types";

const MODES: { value: ManualMode; label: string; description: string }[] = [
  {
    value: "only",
    label: "Só estes trechos",
    description:
      "O job corta exatamente o que você indicou e nada mais — sem análise, varredura ou visão",
  },
  {
    value: "plus",
    label: "Estes + o que a IA achar",
    description:
      "Os trechos indicados entram garantidos, e a análise continua procurando outros",
  },
];

interface Props {
  value: string;
  onChange: (text: string) => void;
  mode: ManualMode;
  onModeChange: (mode: ManualMode) => void;
  /** Compilado ligado muda o que a ordem dos trechos significa. */
  isCompilation?: boolean;
}

export default function ManualClipsField({
  value,
  onChange,
  mode,
  onModeChange,
  isCompilation,
}: Props) {
  const hasRanges = value.trim().length > 0;

  return (
    <div className="flex flex-col gap-2">
      <label htmlFor="manual-clips" className="text-sm font-medium text-gray-400">
        Trechos indicados por você{" "}
        <span className="text-gray-600 font-normal">(opcional)</span>
      </label>
      <textarea
        id="manual-clips"
        value={value}
        onChange={(e) => onChange(e.target.value)}
        rows={2}
        placeholder="3:24 - 4:10, 12:05 - 12:40"
        className="w-full rounded-lg bg-gray-800 border border-gray-700 px-4 py-3 text-gray-100 placeholder-gray-500 focus:outline-none focus:border-emerald-500 font-mono text-sm"
      />
      <p className="text-xs text-gray-500">
        Um por linha ou separados por vírgula. Aceita <code>3:24</code>,{" "}
        <code>1:02:03</code> ou segundos puros.
        {isCompilation && hasRanges
          ? " No compilado, a ordem que você digitar é a ordem da montagem."
          : ""}
      </p>

      {hasRanges && (
        <div className="flex flex-col gap-2 pt-1">
          <div className="flex gap-2 flex-wrap">
            {MODES.map((m) => (
              <button
                key={m.value}
                type="button"
                onClick={() => onModeChange(m.value)}
                title={m.description}
                className={`px-4 py-2 rounded-lg text-sm font-medium transition-colors border ${
                  mode === m.value
                    ? "bg-emerald-500 border-emerald-500 text-white"
                    : "bg-gray-800 border-gray-700 text-gray-300 hover:border-emerald-600"
                }`}
              >
                {m.label}
              </button>
            ))}
          </div>
          <p className="text-xs text-gray-500">
            {MODES.find((m) => m.value === mode)?.description}.
          </p>
        </div>
      )}
    </div>
  );
}
