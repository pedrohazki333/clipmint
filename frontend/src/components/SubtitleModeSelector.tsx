"use client";

import type { SubtitleMode } from "@/lib/types";

const MODES: { value: SubtitleMode; label: string; description: string }[] = [
  {
    value: "word_highlight",
    label: "Palavra a palavra",
    description:
      "A fala aparece inteira e cada palavra acende em amarelo no instante em que é dita.",
  },
  {
    value: "traditional",
    label: "Blocos",
    description:
      "Uma frase por vez, em bloco, trocando a cada pausa. Todo o texto na mesma cor.",
  },
  {
    value: "none",
    label: "Sem legenda",
    description:
      "Só o vídeo. Quem assiste sem som não acompanha o que está sendo dito.",
  },
];

/** Para o resumo de uma linha, quando os ajustes estão fechados. */
export const SUBTITLE_LABELS: Record<SubtitleMode, string> = Object.fromEntries(
  MODES.map((m) => [m.value, m.label]),
) as Record<SubtitleMode, string>;

interface Props {
  value: SubtitleMode;
  onChange: (mode: SubtitleMode) => void;
}

/**
 * Segmentado de três, com a explicação da opção ESCOLHIDA embaixo.
 *
 * Antes cada botão levava a descrição num `title`, que no celular — onde não há
 * cursor para pousar — simplesmente não existia: sobravam três nomes, e
 * "Tradicional" não diz o que muda na tela. Uma linha só, a da escolha atual,
 * em vez de três em paralelo: as outras duas se leem trocando a seleção, que é
 * de graça e mostra o resultado na prévia ao lado.
 */
export default function SubtitleModeSelector({ value, onChange }: Props) {
  const atual = MODES.find((m) => m.value === value);

  return (
    <div className="flex flex-col gap-2">
      <div className="grid grid-cols-3 gap-2">
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
        <p className="text-label leading-relaxed text-ink-dim">
          {atual.description}
        </p>
      )}
    </div>
  );
}
