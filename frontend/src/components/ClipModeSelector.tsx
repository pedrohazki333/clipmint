"use client";

import type { ClipMode } from "@/lib/types";

const MODES: { value: ClipMode; label: string; description: string }[] = [
  {
    value: "individual",
    label: "Clipes individuais",
    description:
      "Cada momento vira um clipe separado, e cada um se explica sozinho.",
  },
  {
    value: "compilation",
    label: "Compilado",
    description:
      "Vários momentos da mesma sessão emendados num vídeo só, abrindo pela reação mais forte. Se o vídeo não tiver material que se sustente, o job volta a gerar clipes individuais sozinho.",
  },
];

/** Para o resumo de uma linha, quando os ajustes estão fechados. */
export const CLIP_MODE_LABELS: Record<ClipMode, string> = Object.fromEntries(
  MODES.map((m) => [m.value, m.label]),
) as Record<ClipMode, string>;

interface Props {
  value: ClipMode;
  onChange: (mode: ClipMode) => void;
}

/**
 * Segmentado de dois, com a explicação da opção escolhida embaixo.
 *
 * Sem rótulo próprio: quem nomeia o controle é o cartão que o contém. Enquanto
 * cada seletor trazia o seu, a tela tinha dois títulos empilhados dizendo a
 * mesma coisa.
 */
export default function ClipModeSelector({ value, onChange }: Props) {
  const atual = MODES.find((m) => m.value === value);

  return (
    <div className="flex flex-col gap-2">
      <div className="grid grid-cols-2 gap-2">
        {MODES.map((mode) => {
          const ativo = value === mode.value;
          return (
            <button
              key={mode.value}
              type="button"
              onClick={() => onChange(mode.value)}
              aria-pressed={ativo}
              className={`rounded-sm border px-2 py-2.5 text-body font-medium transition-colors ${
                ativo
                  ? "border-mint bg-mint-soft text-mint"
                  : "border-line bg-inset text-ink hover:border-line-strong hover:bg-hover"
              }`}
            >
              {mode.label}
            </button>
          );
        })}
      </div>
      {atual && (
        <p className="text-label leading-relaxed text-ink-dim">{atual.description}</p>
      )}
    </div>
  );
}
