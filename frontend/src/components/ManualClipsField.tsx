"use client";

import type { ManualMode } from "@/lib/types";

const MODES: { value: ManualMode; label: string; description: string }[] = [
  {
    value: "only",
    label: "Só estes trechos",
    description:
      "O job corta exatamente o que você indicou e nada mais — sem análise, varredura ou visão.",
  },
  {
    value: "plus",
    label: "Estes + o que a IA achar",
    description:
      "Os trechos indicados entram garantidos, e a análise continua procurando outros.",
  },
];

interface Props {
  value: string;
  onChange: (text: string) => void;
  mode: ManualMode;
  onModeChange: (mode: ManualMode) => void;
  /** Compilado ligado muda o que a ordem dos trechos significa. */
  isCompilation?: boolean;
  disabled?: boolean;
}

/**
 * Os trechos que a pessoa já sabe que quer.
 *
 * Mora junto do link, e não no meio dos ajustes, porque é a mesma pergunta:
 * "que vídeo, e que parte dele". Os dois modos só aparecem depois que existe
 * pelo menos um trecho digitado — antes disso a escolha não tem objeto.
 */
export default function ManualClipsField({
  value,
  onChange,
  mode,
  onModeChange,
  isCompilation,
  disabled,
}: Props) {
  const hasRanges = value.trim().length > 0;

  return (
    <div className="flex flex-col gap-2">
      <label htmlFor="manual-clips" className="text-body font-medium text-ink">
        Trechos indicados por você{" "}
        <span className="font-normal text-ink-muted">(opcional)</span>
      </label>
      <textarea
        id="manual-clips"
        value={value}
        onChange={(e) => onChange(e.target.value)}
        rows={2}
        disabled={disabled}
        placeholder="3:24 - 4:10, 12:05 - 12:40"
        className="w-full rounded-sm border border-line bg-inset px-4 py-2.5 font-mono text-body text-ink placeholder-ink-muted outline-none transition-colors focus:border-mint disabled:opacity-50"
      />
      <p className="text-label leading-relaxed text-ink-muted">
        Um por linha ou separados por vírgula. Aceita <code>3:24</code>,{" "}
        <code>1:02:03</code> ou segundos puros. Em branco, a análise escolhe os
        trechos sozinha.
        {isCompilation && hasRanges
          ? " No compilado, a ordem que você digitar é a ordem da montagem."
          : ""}
      </p>

      {hasRanges && (
        <div className="mt-1 flex flex-col gap-2">
          <div className="grid grid-cols-2 gap-2">
            {MODES.map((m) => {
              const ativo = mode === m.value;
              return (
                <button
                  key={m.value}
                  type="button"
                  onClick={() => onModeChange(m.value)}
                  aria-pressed={ativo}
                  className={`rounded-sm border px-2 py-2.5 text-body font-medium transition-colors ${
                    ativo
                      ? "border-mint bg-mint-soft text-mint"
                      : "border-line bg-inset text-ink hover:border-line-strong hover:bg-hover"
                  }`}
                >
                  {m.label}
                </button>
              );
            })}
          </div>
          <p className="text-label leading-relaxed text-ink-dim">
            {MODES.find((m) => m.value === mode)?.description}
          </p>
        </div>
      )}
    </div>
  );
}
