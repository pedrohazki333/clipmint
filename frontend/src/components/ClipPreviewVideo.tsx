"use client";

import { useEffect, useRef, useState } from "react";

import { getClipPreviewUrl } from "@/lib/api";

/**
 * Os três primeiros segundos do clipe, em looping, no cartão.
 *
 * Toca sozinho quando entra na tela e pausa quando sai. Não é enfeite: com uma
 * dúzia de cartões, deixar todos os vídeos rodando ao mesmo tempo gasta bateria
 * e trava a rolagem no celular — o `IntersectionObserver` mantém em movimento
 * só o que está sendo olhado.
 *
 * Três coisas que o navegador exige para tocar sem clique: `muted`,
 * `playsInline` (sem ele o iPhone abre em tela cheia) e uma chamada a `play()`
 * que pode ser recusada — daí o `.catch` vazio, que é o caminho normal e não
 * um erro.
 *
 * Quem pediu menos movimento no sistema não recebe movimento nenhum: fica o
 * primeiro quadro parado, que já mostra o enquadramento.
 */
export default function ClipPreviewVideo({
  clipId,
  /** Mostrado no canto, sobre a imagem. */
  legenda,
}: {
  clipId: string;
  legenda?: string;
}) {
  const ref = useRef<HTMLVideoElement>(null);
  /** 404: clipe gerado antes das prévias, ou arquivo já expirado. */
  const [semPrevia, setSemPrevia] = useState(false);

  useEffect(() => {
    const el = ref.current;
    if (!el || semPrevia) return;

    const quieto = window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;
    if (quieto) return;

    const observer = new IntersectionObserver(
      ([entrada]) => {
        if (entrada.isIntersecting) el.play().catch(() => {});
        else el.pause();
      },
      { threshold: 0.25 },
    );
    observer.observe(el);
    return () => observer.disconnect();
  }, [semPrevia]);

  return (
    <div className="relative aspect-[9/16] w-full overflow-hidden rounded-sm border border-line bg-inset">
      {semPrevia ? (
        <div className="flex h-full w-full items-center justify-center text-ink-muted">
          <svg
            viewBox="0 0 24 24"
            className="h-5 w-5"
            fill="none"
            stroke="currentColor"
            strokeWidth="1.5"
            aria-hidden="true"
          >
            <rect x="3" y="4" width="18" height="16" rx="2" />
            <path d="M8 4v16M16 4v16" />
          </svg>
        </div>
      ) : (
        <video
          ref={ref}
          src={getClipPreviewUrl(clipId)}
          muted
          loop
          playsInline
          preload="metadata"
          onError={() => setSemPrevia(true)}
          className="h-full w-full object-cover"
          aria-label="Prévia dos primeiros segundos do clipe"
        />
      )}

      {legenda && (
        <span className="tabular absolute bottom-1 right-1 rounded-sm bg-base/80 px-1.5 py-0.5 text-[10px] leading-none text-ink">
          {legenda}
        </span>
      )}
    </div>
  );
}
