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
      <label htmlFor="manual-clips" className="text-body font-medium text-ink-dim">
        Trechos indicados por você{" "}
        <span className="text-ink-muted font-normal">(opcional)</span>
      </label>
      <textarea
        id="manual-clips"
        value={value}
        onChange={(e) => onChange(e.target.value)}
        rows={2}
        placeholder="3:24 - 4:10, 12:05 - 12:40"
        className="w-full rounded-sm bg-inset border border-line px-4 py-3 text-ink placeholder-ink-muted focus:outline-none focus:border-mint font-mono text-body"
      />
      <p className="text-label text-ink-dim">
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
                className={`px-4 py-2 rounded-sm text-body font-medium transition-colors border ${
                  mode === m.value
                    ? "bg-mint-strong border-mint text-white"
                    : "bg-inset border-line text-ink hover:border-mint"
                }`}
              >
                {m.label}
              </button>
            ))}
          </div>
          <p className="text-label text-ink-dim">
            {MODES.find((m) => m.value === mode)?.description}.
          </p>
        </div>
      )}
    </div>
  );
}
