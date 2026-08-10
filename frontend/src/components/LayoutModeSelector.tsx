"use client";

import type { LayoutMode } from "@/lib/types";

const MODES: { value: LayoutMode; label: string; description: string }[] = [
  {
    value: "cover",
    label: "Capa + Banner",
    description: "Print expressivo no topo, pílula com o título e o vídeo embaixo (1080x1920)",
  },
  {
    value: "streamer",
    label: "Facecam + Gameplay",
    description: "Live de jogo: webcam em cima, faixa com sua logo e o gameplay embaixo (4K vertical)",
  },
];

interface Props {
  value: LayoutMode;
  onChange: (mode: LayoutMode) => void;
}

export default function LayoutModeSelector({ value, onChange }: Props) {
  return (
    <div className="flex flex-col gap-2">
      <label className="text-sm font-medium text-gray-400">Layout do clipe</label>
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
      {value === "streamer" && (
        <p className="text-xs text-gray-500">
          A posição da webcam é detectada automaticamente no primeiro clipe e reaproveitada nos
          demais. Se o enquadramento sair torto, ajuste a caixa na página do job.
        </p>
      )}
    </div>
  );
}
