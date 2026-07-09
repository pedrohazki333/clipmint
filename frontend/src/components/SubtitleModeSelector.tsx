"use client";

import type { SubtitleMode } from "@/lib/types";

const MODES: { value: SubtitleMode; label: string; description: string }[] = [
  {
    value: "word_highlight",
    label: "Word Highlight",
    description: "Cada palavra destacada em amarelo (estilo TikTok)",
  },
  {
    value: "traditional",
    label: "Tradicional",
    description: "Blocos de texto clássicos",
  },
  {
    value: "none",
    label: "Sem legenda",
    description: "Apenas o vídeo cropado",
  },
];

interface Props {
  value: SubtitleMode;
  onChange: (mode: SubtitleMode) => void;
}

export default function SubtitleModeSelector({ value, onChange }: Props) {
  return (
    <div className="flex flex-col gap-2">
      <label className="text-sm font-medium text-gray-400">Modo de legenda</label>
      <div className="flex gap-2 flex-wrap">
        {MODES.map((mode) => (
          <button
            key={mode.value}
            type="button"
            onClick={() => onChange(mode.value)}
            title={mode.description}
            className={`px-4 py-2 rounded-lg text-sm font-medium transition-colors border ${
              value === mode.value
                ? "bg-emerald-500 border-emerald-500 text-white"
                : "bg-gray-800 border-gray-700 text-gray-300 hover:border-emerald-600"
            }`}
          >
            {mode.label}
          </button>
        ))}
      </div>
    </div>
  );
}
