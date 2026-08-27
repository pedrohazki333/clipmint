"use client";

import { useEffect } from "react";

import { LAYOUT_LABELS, layoutsFor } from "@/lib/layouts";
import type { LayoutMode, SourceType } from "@/lib/types";

/**
 * Escolha do layout, filtrada pela rubrica.
 *
 * Dois modos presumem o tipo de conteúdo e por isso só aparecem onde fazem
 * sentido: a **capa** é escolhida pelo quadro mais expressivo de um rosto
 * falando (num gameplay ela pega uma tela de jogo), e a **facecam empilhada**
 * precisa de uma câmera separada do jogo (num podcast o vídeo inteiro já é a
 * câmera). Mostrar os dois em toda rubrica oferecia uma escolha que o servidor
 * recusa — a regra vive em lib/layouts.ts e é espelhada no backend.
 */

interface Props {
  value: LayoutMode;
  onChange: (mode: LayoutMode) => void;
  /** Rubrica escolhida. É ela que decide quais layouts aparecem. */
  source: SourceType;
}

export default function LayoutModeSelector({ value, onChange, source }: Props) {
  const disponiveis = layoutsFor(source);

  // Trocar a rubrica pode invalidar o layout selecionado (de podcast para
  // gameplay, "capa" deixa de existir). Cai no primeiro disponível em vez de
  // manter uma escolha que o servidor recusaria no envio.
  useEffect(() => {
    if (!disponiveis.includes(value)) onChange(disponiveis[0]);
  }, [source, value, disponiveis, onChange]);

  const atual = LAYOUT_LABELS[value];

  return (
    <div className="flex flex-col gap-2">
      <label className="text-body font-medium text-ink-dim">Layout do clipe</label>
      <div className="flex flex-wrap gap-2">
        {disponiveis.map((modo) => (
          <button
            key={modo}
            type="button"
            onClick={() => onChange(modo)}
            title={LAYOUT_LABELS[modo].descricao}
            aria-pressed={value === modo}
            className={`rounded-sm border px-4 py-2 text-body font-medium transition-colors ${
              value === modo
                ? "border-mint bg-mint-strong text-base"
                : "border-line bg-inset text-ink hover:border-mint"
            }`}
          >
            {LAYOUT_LABELS[modo].nome}
          </button>
        ))}
      </div>

      <p className="text-label text-ink-dim">{atual?.descricao}</p>

      {value === "streamer" && (
        <p className="text-label text-ink-dim">
          A posição da webcam é detectada no primeiro clipe e reaproveitada nos
          demais. Se o enquadramento sair torto, ajuste a caixa na página do job.
        </p>
      )}
      {value === "crop" && (
        <p className="text-label text-ink-dim">
          O recorte é centralizado e igual em todo clipe — não acompanha o rosto.
        </p>
      )}
      {value === "original" && (
        <p className="text-label text-ink-dim">
          Sai na proporção e na resolução do vídeo de origem. Um 16:9 continua
          16:9, então não é o formato das plataformas de vertical.
        </p>
      )}
    </div>
  );
}
