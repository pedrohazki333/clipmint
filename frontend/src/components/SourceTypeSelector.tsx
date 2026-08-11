"use client";

import type { SourceType } from "@/lib/types";

const TYPES: { value: SourceType; label: string; description: string }[] = [
  {
    value: "podcast",
    label: "Podcast",
    description:
      "Avalia gancho verbal, arco de resolução, frase-momento e potencial de debate",
  },
  {
    value: "gameplay",
    label: "Gameplay",
    description:
      "Avalia pico visual, reviravolta, legibilidade sem som e reação do jogador",
  },
  {
    value: "siege",
    label: "Siege X",
    description:
      "Avalia sequência de eliminações, abate rápido de um tiro, clutch e treta na call",
  },
];

interface Props {
  value: SourceType;
  onChange: (type: SourceType) => void;
  /** True quando o valor veio do layout e não de uma escolha explícita. */
  isInferred?: boolean;
}

export default function SourceTypeSelector({ value, onChange, isInferred }: Props) {
  return (
    <div className="flex flex-col gap-2">
      <label className="text-sm font-medium text-gray-400">Tipo de conteúdo</label>
      <div className="flex gap-2 flex-wrap">
        {TYPES.map((type) => (
          <button
            key={type.value}
            type="button"
            onClick={() => onChange(type.value)}
            title={type.description}
            className={`px-4 py-2 rounded-lg text-sm font-medium transition-colors border ${
              value === type.value
                ? "bg-emerald-500 border-emerald-500 text-white"
                : "bg-gray-800 border-gray-700 text-gray-300 hover:border-emerald-600"
            }`}
          >
            {type.label}
          </button>
        ))}
      </div>
      <p className="text-xs text-gray-500">
        {isInferred ? "Sugerido pelo layout. " : ""}
        Define os critérios da análise e em qual conta o clipe entra no cronograma de
        postagem.
      </p>
    </div>
  );
}
