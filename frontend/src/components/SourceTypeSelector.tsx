"use client";

import type { SourceType } from "@/lib/types";
import { PUBLIC_NICHES } from "@/lib/features";
import { PERSONAL_NICHES } from "@/personal";

// A lista de nichos é a do build: no público, PERSONAL_NICHES vem vazio e o
// seletor mostra só as contas que o backend aceita (ver src/lib/features.ts).
const TYPES = [...PUBLIC_NICHES, ...PERSONAL_NICHES];

interface Props {
  value: SourceType;
  onChange: (type: SourceType) => void;
  /** True quando o valor veio do layout e não de uma escolha explícita. */
  isInferred?: boolean;
}

export default function SourceTypeSelector({ value, onChange, isInferred }: Props) {
  return (
    <div className="flex flex-col gap-2">
      <label className="text-body font-medium text-ink-dim">Tipo de conteúdo</label>
      <div className="flex gap-2 flex-wrap">
        {TYPES.map((type) => (
          <button
            key={type.source}
            type="button"
            onClick={() => onChange(type.source)}
            title={type.description}
            className={`px-4 py-2 rounded-sm text-body font-medium transition-colors border ${
              value === type.source
                ? "bg-mint-strong border-mint text-white"
                : "bg-inset border-line text-ink hover:border-mint"
            }`}
          >
            {type.title}
          </button>
        ))}
      </div>
      {/* A menção ao cronograma saiu daqui: a fila de postagem é da versão
          pessoal, e no build público este texto prometia algo que não existe. O
          que a rubrica faz — decidir os critérios da análise — vale nos dois. */}
      <p className="text-label text-ink-dim">
        {isInferred ? "Sugerido pelo layout. " : ""}
        Define os critérios que a análise usa para escolher os melhores trechos.
      </p>
    </div>
  );
}
