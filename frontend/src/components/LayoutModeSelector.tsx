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
 *
 * Cada opção é um cartão com um esquema do enquadramento, e não uma pílula com
 * o nome. "Capa + banner" e "Crop vertical" não dizem nada a quem nunca viu o
 * resultado; o desenho das faixas diz, e diz antes de gastar um crédito para
 * descobrir. O esquema é abstrato de propósito — proporções do render, sem
 * imitar um clipe pronto, que é papel da prévia ao lado.
 */

interface Props {
  value: LayoutMode;
  onChange: (mode: LayoutMode) => void;
  /** Rubrica escolhida. É ela que decide quais layouts aparecem. */
  source: SourceType;
}

/**
 * O esquema de cada layout, em proporção 9:16 como o arquivo final.
 *
 * As alturas seguem as do render (ver ClipPreview): capa ocupa 40% e o banner
 * cai na emenda; no streamer a câmera ocupa 35% e a faixa é a própria costura.
 */
function LayoutThumb({ mode, ativo }: { mode: LayoutMode; ativo: boolean }) {
  const tinta = ativo ? "text-mint" : "text-ink-muted";
  const preenche = ativo ? "fill-mint" : "fill-ink-muted";
  const fraco = ativo ? "fill-mint/25" : "fill-line-strong";

  return (
    <svg
      viewBox="0 0 36 64"
      className={`h-16 w-9 ${tinta}`}
      aria-hidden="true"
    >
      <rect
        x="0.75"
        y="0.75"
        width="34.5"
        height="62.5"
        rx="3"
        className="fill-transparent stroke-current"
        strokeWidth="1.5"
      />
      {mode === "cover" && (
        <>
          <rect x="4" y="4" width="28" height="20" rx="1.5" className={fraco} />
          <rect x="2.5" y="22" width="31" height="7" rx="1" className={preenche} />
          <rect x="4" y="32" width="28" height="28" rx="1.5" className={fraco} />
        </>
      )}
      {mode === "streamer" && (
        <>
          <rect x="4" y="4" width="28" height="18" rx="1.5" className={fraco} />
          <rect x="2.5" y="23" width="31" height="3.5" rx="1" className={preenche} />
          <rect x="4" y="28" width="28" height="32" rx="1.5" className={fraco} />
        </>
      )}
      {mode === "crop" && (
        <>
          <rect x="4" y="4" width="28" height="56" rx="1.5" className={fraco} />
          <path
            d="M11 4v56M25 4v56"
            className="stroke-current"
            strokeWidth="1.25"
            strokeDasharray="3 3"
          />
        </>
      )}
      {mode === "original" && (
        <rect x="4" y="23" width="28" height="18" rx="1.5" className={fraco} />
      )}
    </svg>
  );
}

export default function LayoutModeSelector({ value, onChange, source }: Props) {
  const disponiveis = layoutsFor(source);

  // Trocar a rubrica pode invalidar o layout selecionado (de podcast para
  // gameplay, "capa" deixa de existir). Cai no primeiro disponível em vez de
  // manter uma escolha que o servidor recusaria no envio.
  useEffect(() => {
    if (!disponiveis.includes(value)) onChange(disponiveis[0]);
  }, [source, value, disponiveis, onChange]);

  return (
    <div className="flex flex-col gap-3">
      {/* No celular um cartão por linha, com o esquema à esquerda: três colunas
          de 100px deixariam a descrição em cinco linhas de duas palavras. */}
      <div className="grid grid-cols-1 gap-2 sm:grid-cols-3">
        {disponiveis.map((modo) => {
          const ativo = value === modo;
          return (
            <button
              key={modo}
              type="button"
              onClick={() => onChange(modo)}
              aria-pressed={ativo}
              className={`flex items-center gap-3 rounded-sm border p-3 text-left transition-colors sm:flex-col sm:items-center sm:gap-2 sm:text-center ${
                ativo
                  ? "border-mint bg-mint-soft"
                  : "border-line bg-inset hover:border-line-strong hover:bg-hover"
              }`}
            >
              <LayoutThumb mode={modo} ativo={ativo} />
              <span className="min-w-0">
                <span
                  className={`block text-body font-medium ${ativo ? "text-mint" : "text-ink"}`}
                >
                  {LAYOUT_LABELS[modo].nome}
                </span>
                <span className="mt-0.5 block text-label leading-relaxed text-ink-muted">
                  {LAYOUT_LABELS[modo].descricao}
                </span>
              </span>
            </button>
          );
        })}
      </div>

      {value === "streamer" && (
        <p className="text-label leading-relaxed text-ink-dim">
          A posição da webcam é detectada no primeiro clipe e reaproveitada nos
          demais. Se o enquadramento sair torto, ajuste a caixa na página do job.
        </p>
      )}
      {value === "crop" && (
        <p className="text-label leading-relaxed text-ink-dim">
          O recorte é centralizado e igual em todo clipe — não acompanha o rosto.
        </p>
      )}
      {value === "original" && (
        <p className="text-label leading-relaxed text-ink-dim">
          Sai na proporção e na resolução do vídeo de origem. Um 16:9 continua
          16:9, então não é o formato das plataformas de vertical.
        </p>
      )}
    </div>
  );
}
