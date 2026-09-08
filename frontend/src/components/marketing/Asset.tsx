import { existsSync } from "node:fs";
import { join } from "node:path";

import { SLOTS, type Arte, type Slot, type SlotId } from "./assets";

/**
 * Um lugar para uma arte.
 *
 * Não desenha nada: reserva a proporção, escolhe entre a arte deitada e a em pé
 * conforme a largura, e desiste em favor de um marcador enquanto o arquivo não
 * existe. Todo visual da landing passa por aqui — é o que impede a página de
 * voltar a simular o produto com CSS.
 *
 * A troca desktop/celular é feita por `<source media>`, sem JavaScript: o
 * navegador escolhe antes de baixar, então o celular nunca puxa a arte deitada.
 *
 * Componente de SERVIDOR (usa `node:fs`). Não importe de um componente cliente.
 */

const QUEBRA = "(min-width: 768px)";

export default function Asset({
  slot: id,
  className = "",
  priority = false,
}: {
  slot: SlotId;
  className?: string;
  /** Carrega sem esperar. Só para o que está na primeira tela. */
  priority?: boolean;
}) {
  const slot = SLOTS[id] as Slot;
  const desktop = temArquivo(slot.desktop) ? slot.desktop : null;
  const mobile = slot.mobile && temArquivo(slot.mobile) ? slot.mobile : null;

  // Sem nenhuma das duas artes, o slot vira briefing na tela.
  if (!desktop && !mobile) return <Marcador slot={slot} className={className} />;

  return (
    <div className={`overflow-hidden ${className}`}>
      {slot.formato === "video" ? (
        <Video slot={slot} desktop={desktop} mobile={mobile} />
      ) : (
        <Imagem slot={slot} desktop={desktop} mobile={mobile} priority={priority} />
      )}
    </div>
  );
}

function temArquivo(arte: Arte): boolean {
  return existsSync(join(process.cwd(), "public", arte.src));
}

function Imagem({
  slot,
  desktop,
  mobile,
  priority,
}: {
  slot: Slot;
  desktop: Arte | null;
  mobile: Arte | null;
  priority: boolean;
}) {
  // A arte que o `<img>` aponta é a de fallback: a deitada quando ela existe.
  const principal = desktop ?? mobile!;
  return (
    <picture>
      {mobile && desktop && (
        <source media={`not all and ${QUEBRA}`} srcSet={mobile.src} />
      )}
      {/* eslint-disable-next-line @next/next/no-img-element */}
      <img
        src={principal.src}
        alt={slot.alt}
        width={principal.w}
        height={principal.h}
        loading={priority ? "eager" : "lazy"}
        fetchPriority={priority ? "high" : "auto"}
        decoding={priority ? "sync" : "async"}
        className="h-auto w-full"
      />
    </picture>
  );
}

/**
 * Vídeo mudo, em laço, que toca sozinho.
 *
 * `playsInline` não é opcional: sem ele o iPhone abre o vídeo em tela cheia
 * quando começa a tocar, e a pessoa perde a página. `muted` é o que autoriza o
 * autoplay em todos os navegadores; um vídeo de landing com som seria hostil de
 * qualquer forma.
 *
 * Quem pediu menos movimento ao sistema não recebe laço: aí o vídeo fica no
 * pôster, com o controle à mostra para quem quiser tocar.
 */
function Video({
  slot,
  desktop,
  mobile,
}: {
  slot: Slot;
  desktop: Arte | null;
  mobile: Arte | null;
}) {
  const principal = desktop ?? mobile!;
  return (
    <video
      poster={principal.poster}
      width={principal.w}
      height={principal.h}
      autoPlay
      muted
      loop
      playsInline
      preload="metadata"
      aria-label={slot.alt}
      className="h-auto w-full motion-reduce:[&]:![animation-play-state:paused]"
    >
      {mobile && desktop && (
        <source media={`not all and ${QUEBRA}`} src={mobile.src} type="video/mp4" />
      )}
      <source src={principal.src} type="video/mp4" />
    </video>
  );
}

/**
 * O que aparece enquanto a arte não chegou.
 *
 * Mostra o briefing e o caminho esperado — não um esboço do que a arte deveria
 * ser. Um esboço em CSS aqui seria pior que o vazio: alguém o veria numa
 * captura e acharia que é o desenho final. Foi exatamente esse o erro que este
 * arquivo existe para não repetir.
 */
function Marcador({ slot, className = "" }: { slot: Slot; className?: string }) {
  const { w, h } = slot.desktop;
  return (
    <div
      className={`flex flex-col justify-between gap-6 rounded-md border border-dashed border-line-strong bg-raised p-5 sm:p-7 ${className}`}
      style={{ aspectRatio: `${w} / ${h}` }}
    >
      <div className="flex items-center gap-2">
        <span className="rounded-full border border-line bg-inset px-2 py-0.5 font-mono text-label uppercase tracking-[0.16em] text-mint">
          {slot.formato}
        </span>
        <span className="font-mono text-label uppercase tracking-[0.16em] text-ink-dim">
          {slot.id}
        </span>
      </div>

      <p className="max-w-prose text-body leading-relaxed text-ink-dim">
        {slot.briefing}
      </p>

      <div className="flex flex-col gap-1 font-mono text-label text-ink-dim">
        <span>
          desktop · {w}×{h} · public{slot.desktop.src}
        </span>
        {slot.mobile && (
          <span>
            celular · {slot.mobile.w}×{slot.mobile.h} · public{slot.mobile.src}
          </span>
        )}
      </div>
    </div>
  );
}
