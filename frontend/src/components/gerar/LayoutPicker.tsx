"use client";

import { LAYOUT_LABELS } from "@/lib/layouts";
import type { LayoutMode } from "@/lib/types";
import { SelectedBadge } from "./CaptionPicker";
import { LAYOUT_SHORT } from "./choices";
import { radioKeyDown } from "./radioKeys";

/**
 * O diagrama de cada layout, no quadro vertical do clipe.
 *
 * Tinta é o que é vídeo, coral é o título da marca, menta é a legenda — as
 * mesmas posições da especificação (docs/LAYOUTS_V2.md), simplificadas a blocos.
 */
function Diagrama({ layout }: { layout: LayoutMode }) {
  const video = "var(--color-ink)";
  const videoClaro = "color-mix(in srgb, var(--color-ink) 22%, transparent)";
  const titulo = "var(--color-coral)";
  const legenda = "var(--color-mint-strong)";

  return (
    <svg viewBox="0 0 30 52" className="h-10 w-auto" aria-hidden focusable="false">
      {layout === "original" ? (
        <>
          <rect x="1" y="1" width="28" height="50" rx="3.5" fill="none" stroke={videoClaro} strokeWidth="1.5" />
          <rect x="1.75" y="18" width="26.5" height="15" fill={video} />
          <rect x="7" y="35.5" width="16" height="2.4" rx="1.2" fill={legenda} />
        </>
      ) : layout === "crop" ? (
        <>
          <rect x="1" y="1" width="28" height="50" rx="3.5" fill={video} />
          <path d="M5 8V5h3M22 5h3v3M25 44v3h-3M8 47H5v-3" fill="none" stroke="#fff" strokeWidth="1.4" />
          <rect x="7" y="35.5" width="16" height="2.4" rx="1.2" fill={legenda} />
        </>
      ) : layout === "streamer" ? (
        <>
          <rect x="1" y="1" width="28" height="18" rx="3.5" fill={video} />
          <rect x="1" y="17" width="28" height="2" fill={video} />
          <rect x="1" y="19.5" width="28" height="3" fill={titulo} />
          <rect x="1" y="23" width="28" height="28" rx="3.5" fill={videoClaro} />
          <rect x="1" y="23" width="28" height="3" fill={videoClaro} />
          <rect x="7" y="40" width="16" height="2.4" rx="1.2" fill={legenda} />
        </>
      ) : layout === "cover" ? (
        <>
          <rect x="1" y="1" width="28" height="20" rx="3.5" fill={videoClaro} />
          <rect x="1" y="18" width="28" height="3" fill={videoClaro} />
          <rect x="1" y="21" width="28" height="8" fill={video} />
          <rect x="1" y="21" width="28" height="1.1" fill={titulo} />
          <rect x="1" y="27.9" width="28" height="1.1" fill={titulo} />
          <rect x="4" y="23.6" width="14" height="2.6" rx="0.6" fill="#fff" />
          <rect x="1" y="29" width="28" height="22" rx="3.5" fill={video} />
          <rect x="1" y="29" width="28" height="3" fill={video} />
          <rect x="7" y="39" width="16" height="2.4" rx="1.2" fill={legenda} />
        </>
      ) : (
        <>
          <rect x="1" y="1" width="28" height="50" rx="3.5" fill={video} />
          <rect x="4" y="7" width="17" height="3.2" fill={titulo} />
          <rect x="4" y="11.2" width="12" height="3.2" fill="#fff" />
          <rect x="7" y="36" width="16" height="2.4" rx="1.2" fill={legenda} />
        </>
      )}
    </svg>
  );
}

export default function LayoutPicker({
  value,
  onChange,
  available,
  labelledBy,
}: {
  value: LayoutMode;
  onChange: (layout: LayoutMode) => void;
  /** Os layouts que a rubrica (ou o perfil) aceita, na ordem de exibição. */
  available: LayoutMode[];
  labelledBy: string;
}) {
  return (
    <div
      role="radiogroup"
      aria-labelledby={labelledBy}
      className="-mx-1 flex snap-x gap-2.5 overflow-x-auto px-1 pb-1 pt-2 sm:grid sm:overflow-visible"
      style={{ gridTemplateColumns: `repeat(${available.length}, minmax(0, 1fr))` }}
    >
      {available.map((layout) => {
        const ativo = value === layout;
        return (
          <button
            key={layout}
            type="button"
            role="radio"
            aria-checked={ativo}
            tabIndex={ativo ? 0 : -1}
            title={LAYOUT_LABELS[layout].descricao}
            onClick={() => onChange(layout)}
            onKeyDown={(e) => radioKeyDown(e, available, value, onChange)}
            className={`group relative flex w-[6.25rem] flex-shrink-0 snap-start flex-col items-center gap-2 rounded-lg border-2 bg-raised px-1 pb-2 pt-2.5 transition-colors duration-150 sm:w-auto ${
              ativo ? "border-mint-strong" : "border-transparent hover:border-line-strong"
            }`}
          >
            <SelectedBadge on={ativo} />
            <Diagrama layout={layout} />
            <span
              className={`whitespace-nowrap text-center text-[0.8125rem] leading-tight ${
                ativo ? "font-semibold text-ink" : "text-ink-dim group-hover:text-ink"
              }`}
            >
              {LAYOUT_SHORT[layout]}
            </span>
          </button>
        );
      })}
    </div>
  );
}
