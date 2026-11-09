"use client";

import type { CSSProperties } from "react";
import { Check } from "lucide-react";

import { DEFAULT_BRAND, isHex, type ClipStyle } from "@/lib/clipStyle";
import { CAPTION_CHOICES, type CaptionChoice } from "./choices";
import { radioKeyDown } from "./radioKeys";

/**
 * O selo de "escolhido". A menta sozinha não basta para dizer o que está
 * selecionado — sobre o papel claro ela fica a 1,3:1 — então a escolha também
 * ganha a marca do check, em tinta.
 */
export function SelectedBadge({ on }: { on: boolean }) {
  return (
    <span
      aria-hidden
      className={`absolute -right-2 -top-2 z-10 flex h-6 w-6 items-center justify-center rounded-full bg-mint-strong text-ink ring-[3px] ring-[var(--color-inset)] transition-[opacity,transform] duration-150 ${
        on ? "scale-100 opacity-100" : "scale-75 opacity-0"
      }`}
    >
      <Check className="h-3.5 w-3.5" strokeWidth={3} />
    </span>
  );
}

/** A tipografia real da legenda (Archivo 800 a 92%), como sai no clipe. */
function fonteDaLegenda(fonte: string): CSSProperties {
  return fonte === "archivo"
    ? { fontFamily: "var(--font-clip)", fontWeight: 800, fontStretch: "92%" }
    : { fontFamily: "var(--font-clip)", fontWeight: 800 };
}

const CONTORNO: CSSProperties = {
  color: "#fff",
  WebkitTextStroke: "4px #000",
  paintOrder: "stroke fill",
};

/**
 * A amostra de cada legenda: as mesmas regras do render, em miniatura.
 * "Dinâmica" é o destaque por cor; "Caixa", a palavra numa caixa na cor da
 * legenda com o texto escuro; "Clássica", o bloco branco com contorno.
 */
function Amostra({ value, style }: { value: CaptionChoice; style: ClipStyle }) {
  const corLegenda = isHex(style.legenda.cor) ? style.legenda.cor : DEFAULT_BRAND;
  const base: CSSProperties = {
    ...fonteDaLegenda(style.fonte),
    fontSize: 21,
    lineHeight: 1.04,
    letterSpacing: "0.01em",
  };

  if (value === "nenhuma") {
    return (
      <span className="flex flex-col items-center gap-1.5" aria-hidden>
        <span className="h-[3px] w-14 rounded-full bg-white/25" />
        <span className="h-[3px] w-9 rounded-full bg-white/15" />
      </span>
    );
  }

  if (value === "classica") {
    return (
      <span style={base} className="flex flex-col items-center whitespace-nowrap uppercase" aria-hidden>
        <span style={CONTORNO}>fala</span>
        <span style={CONTORNO}>séria</span>
      </span>
    );
  }

  if (value === "caixa") {
    return (
      <span style={base} className="flex flex-col items-center gap-[0.08em] whitespace-nowrap uppercase" aria-hidden>
        <span style={CONTORNO}>fala</span>
        <span
          style={{
            background: corLegenda,
            color: "#0B0B0C",
            padding: "0.04em 0.24em",
            borderRadius: "0.24em",
          }}
        >
          séria
        </span>
      </span>
    );
  }

  return (
    <span style={base} className="flex flex-col items-center whitespace-nowrap uppercase" aria-hidden>
      <span style={CONTORNO}>fala</span>
      <span style={{ ...CONTORNO, color: corLegenda }}>séria</span>
    </span>
  );
}

export default function CaptionPicker({
  value,
  onChange,
  style,
  labelledBy,
}: {
  value: CaptionChoice;
  onChange: (value: CaptionChoice) => void;
  /** O estilo em vigor (do perfil ou o padrão): cor e fonte reais da legenda. */
  style: ClipStyle;
  labelledBy: string;
}) {
  return (
    <div
      role="radiogroup"
      aria-labelledby={labelledBy}
      className="grid grid-cols-2 gap-3 pt-2 sm:grid-cols-4"
    >
      {CAPTION_CHOICES.map((opcao) => {
        const ativo = value === opcao.value;
        return (
          <button
            key={opcao.value}
            type="button"
            role="radio"
            aria-checked={ativo}
            tabIndex={ativo ? 0 : -1}
            title={opcao.descricao}
            onClick={() => onChange(opcao.value)}
            onKeyDown={(e) =>
              radioKeyDown(e, CAPTION_CHOICES.map((c) => c.value), value, onChange)
            }
            className={`group relative flex min-w-0 flex-col overflow-visible rounded-lg border-2 p-1 text-left transition-colors duration-150 ${
              ativo ? "border-mint-strong bg-raised" : "border-transparent hover:border-line-strong"
            }`}
          >
            <SelectedBadge on={ativo} />
            <span className="flex h-16 items-center justify-center overflow-hidden rounded-md bg-[#1d1d20]">
              <Amostra value={opcao.value} style={style} />
            </span>
            <span
              className={`px-1 pb-0.5 pt-1.5 text-center text-body ${
                ativo ? "font-semibold text-ink" : "text-ink-dim group-hover:text-ink"
              }`}
            >
              {opcao.nome}
            </span>
          </button>
        );
      })}
    </div>
  );
}
