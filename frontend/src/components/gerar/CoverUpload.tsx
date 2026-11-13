"use client";

import { useId, useRef, useState } from "react";
import { AlertTriangle, ImagePlus, Loader2, X } from "lucide-react";

import { getApiErrorMessage, uploadCover } from "@/lib/api";
import { MEASURES } from "@/lib/clipStyle";

/** O quadro da capa no clipe: a largura toda, do topo até a faixa do título. */
export const COVER_W = MEASURES.canvasW;
export const COVER_H = MEASURES.bandY;

export interface CapaEnviada {
  /** O id que o pedido de geração leva em `cover_upload_id`. */
  id: string;
  /** Endereço local da imagem, para a prévia. */
  url: string;
  nome: string;
  largura: number;
  altura: number;
}

/**
 * A capa do layout "Capa + faixa", enviada pela pessoa.
 *
 * A imagem sobe assim que é escolhida — o pedido de gerar leva só o id. O que a
 * tela mostra é o mesmo recorte que o servidor faz: pelo centro, até encher o
 * quadro de 1080 × 800 sem esticar. Por isso a medida fica à vista antes do
 * envio: quem faz a arte nessa medida vê exatamente a arte no clipe.
 */
export default function CoverUpload({
  value,
  onChange,
  onUploading,
}: {
  value: CapaEnviada | null;
  onChange: (capa: CapaEnviada | null) => void;
  /** Enquanto sobe, gerar espera: o pedido precisa do id. */
  onUploading?: (enviando: boolean) => void;
}) {
  const inputId = useId();
  const input = useRef<HTMLInputElement>(null);
  const [enviando, setEnviando] = useState(false);
  const [erro, setErro] = useState("");

  async function escolher(arquivo: File | undefined) {
    if (!arquivo) return;
    setErro("");
    setEnviando(true);
    onUploading?.(true);
    try {
      const r = await uploadCover(arquivo);
      onChange({
        id: r.id,
        url: URL.createObjectURL(arquivo),
        nome: arquivo.name,
        largura: r.width,
        altura: r.height,
      });
    } catch (err) {
      setErro(getApiErrorMessage(err, "Não foi possível enviar a imagem."));
    } finally {
      setEnviando(false);
      onUploading?.(false);
      if (input.current) input.current.value = "";
    }
  }

  const proporcaoDiferente =
    value && Math.abs(value.largura / value.altura - COVER_W / COVER_H) > 0.02;
  const pequena = value && (value.largura < COVER_W || value.altura < COVER_H);

  return (
    <div className="flex flex-col gap-3 rounded-md border border-line bg-raised p-3.5 sm:p-4">
      <div className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1">
        <label htmlFor={inputId} className="text-body font-semibold text-ink">
          Capa do clipe <span className="font-normal text-ink-muted">(opcional)</span>
        </label>
        <span className="text-label text-ink-muted">
          Sem capa, usamos a reação mais forte de cada clipe.
        </span>
      </div>

      <div className="flex flex-col gap-4 sm:flex-row sm:items-start">
        {/* O lugar da capa no clipe: o quadro de cima, encostado na faixa. */}
        <div
          className="relative mx-auto w-[6.75rem] flex-shrink-0 overflow-hidden rounded-[5px] bg-ink sm:mx-0"
          style={{ aspectRatio: `${MEASURES.canvasW} / ${MEASURES.canvasH}` }}
          aria-hidden
        >
          <div
            className="absolute inset-x-0 top-0 overflow-hidden"
            style={{ height: `${(COVER_H / MEASURES.canvasH) * 100}%` }}
          >
            {value ? (
              // eslint-disable-next-line @next/next/no-img-element
              <img src={value.url} alt="" className="h-full w-full object-cover" />
            ) : (
              <div className="flex h-full items-center justify-center border border-dashed border-white/40 bg-white/5">
                <ImagePlus className="h-4 w-4 text-white/60" />
              </div>
            )}
          </div>
          <div
            className="absolute inset-x-0 bg-coral"
            style={{
              top: `${(MEASURES.bandY / MEASURES.canvasH) * 100}%`,
              height: `${(MEASURES.bandH / MEASURES.canvasH) * 100}%`,
            }}
          />
          <div
            className="absolute inset-x-0 bottom-0 bg-white/10"
            style={{ top: `${((MEASURES.bandY + MEASURES.bandH) / MEASURES.canvasH) * 100}%` }}
          />
        </div>

        <div className="flex min-w-0 flex-1 flex-col gap-3">
          {/* A medida, para quem vai fazer a arte. */}
          <div>
            <span className="block text-label font-semibold uppercase tracking-[0.08em] text-ink-muted">
              Tamanho da capa
            </span>
            <output
              htmlFor={inputId}
              className="tabular mt-1 inline-flex items-center gap-2 rounded-md border border-line-strong bg-base px-3 py-1.5 text-body font-semibold text-ink"
            >
              {COVER_W} × {COVER_H} px
              <span className="font-normal text-ink-muted">· 27:20</span>
            </output>
            <p className="mt-1.5 text-label text-ink-muted">
              Ocupa toda a largura, do topo do clipe até a faixa do título. Outra proporção é
              recortada pelo centro.
            </p>
          </div>

          <input
            ref={input}
            id={inputId}
            type="file"
            accept="image/png,image/jpeg,image/webp"
            className="sr-only"
            onChange={(e) => escolher(e.target.files?.[0])}
            disabled={enviando}
          />

          {value ? (
            <div className="flex min-w-0 flex-wrap items-center gap-2">
              <span className="min-w-0 truncate text-body text-ink">
                {value.nome}{" "}
                <span className="tabular text-label text-ink-muted">
                  {value.largura} × {value.altura}
                </span>
              </span>
              <button
                type="button"
                onClick={() => input.current?.click()}
                className="text-body font-medium text-ink underline decoration-line-strong underline-offset-4 hover:decoration-ink"
              >
                Trocar
              </button>
              <button
                type="button"
                onClick={() => onChange(null)}
                className="inline-flex items-center gap-1 text-body text-ink-dim hover:text-danger"
              >
                <X className="h-3.5 w-3.5" aria-hidden />
                Remover
              </button>
            </div>
          ) : (
            <button
              type="button"
              onClick={() => input.current?.click()}
              disabled={enviando}
              className="inline-flex min-h-10 items-center justify-center gap-2 self-start rounded-md border border-ink/80 px-4 text-body font-semibold text-ink transition-colors hover:bg-ink hover:text-base disabled:opacity-50"
            >
              {enviando ? (
                <Loader2 className="h-4 w-4 animate-spin" aria-hidden />
              ) : (
                <ImagePlus className="h-4 w-4" aria-hidden />
              )}
              {enviando ? "Enviando..." : "Enviar capa"}
            </button>
          )}

          {value && (proporcaoDiferente || pequena) && (
            <p className="flex items-start gap-2 text-label text-running">
              <AlertTriangle className="mt-px h-3.5 w-3.5 flex-shrink-0" aria-hidden />
              <span>
                {proporcaoDiferente && "A imagem não está em 27:20: as bordas serão cortadas, como na prévia. "}
                {pequena && `Menor que ${COVER_W} × ${COVER_H}: vai ser ampliada e pode perder nitidez.`}
              </span>
            </p>
          )}
          {erro && (
            <p role="alert" className="text-label text-danger">
              {erro}
            </p>
          )}
        </div>
      </div>
    </div>
  );
}
