"use client";

import type { ClipMode } from "@/lib/types";

const MODES: { value: ClipMode; label: string; description: string }[] = [
  {
    value: "individual",
    label: "Clipes individuais",
    description:
      "Um clipe por momento, cada um se explicando sozinho — o modo de sempre",
  },
  {
    value: "compilation",
    label: "Compilado",
    description:
      "Procura vários momentos da mesma sessão e emenda num vídeo só, abrindo pela reação mais forte",
  },
];

interface Props {
  value: ClipMode;
  onChange: (mode: ClipMode) => void;
}

export default function ClipModeSelector({ value, onChange }: Props) {
  return (
    <div className="flex flex-col gap-2">
      <label className="text-sm font-medium text-gray-400">Formato</label>
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
      <p className="text-xs text-gray-500">
        {value === "compilation"
          ? "Se o vídeo não tiver material que se sustente como compilado, o job volta a gerar clipes individuais sozinho."
          : "Cada momento vira um clipe separado."}
      </p>
    </div>
  );
}
