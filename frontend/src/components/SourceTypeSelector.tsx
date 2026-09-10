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

/** Sem rótulo próprio: quem nomeia o controle é o cartão que o contém. */
export default function SourceTypeSelector({ value, onChange, isInferred }: Props) {
  const atual = TYPES.find((t) => t.source === value);

  return (
    <div className="flex flex-col gap-2">
      <div className="flex flex-wrap gap-2">
        {TYPES.map((type) => {
          const ativo = value === type.source;
          return (
            <button
              key={type.source}
              type="button"
              onClick={() => onChange(type.source)}
              aria-pressed={ativo}
              className={`rounded-sm border px-4 py-2.5 text-body font-medium transition-colors ${
                ativo
                  ? "border-mint bg-mint-soft text-mint"
                  : "border-line bg-inset text-ink hover:border-line-strong hover:bg-hover"
              }`}
            >
              {type.title}
            </button>
          );
        })}
      </div>
      {/* A menção ao cronograma saiu daqui: a fila de postagem é da versão
          pessoal, e no build público este texto prometia algo que não existe. O
          que a rubrica faz — decidir os critérios da análise — vale nos dois. */}
      <p className="text-label leading-relaxed text-ink-dim">
        {isInferred ? "Sugerido pelo layout. " : ""}
        {atual?.description ??
          "Define os critérios que a análise usa para escolher os melhores trechos."}
      </p>
    </div>
  );
}
