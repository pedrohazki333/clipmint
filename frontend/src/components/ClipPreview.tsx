"use client";

import { useEffect, useState } from "react";

import { fontStack } from "@/components/FontField";
import type { BrandDraft } from "@/lib/brand";
import type { LayoutMode, SubtitleMode } from "@/lib/types";

/**
 * O clipe, como ele vai sair — desenhado ao vivo enquanto se configura.
 *
 * ESPELHO de `backend/app/services/{clipper,layout,subtitler}.py`. Os números
 * abaixo não foram estimados no olho: saíram de rodar o próprio código de
 * render e medir o resultado (banner de verdade: 1080×222px; faixa: 1080×54px;
 * `streamer_geometry()` para o modo gameplay). A primeira versão deste arquivo
 * chutou tudo isso e errou em quase tudo — o banner era uma pílula estreita e
 * arredondada quando na verdade é uma faixa de largura cheia com cantos vivos,
 * a faixa da conta era um selo centralizado quando é o @ repetido de ponta a
 * ponta, e a legenda estava em caixa alta, que o render não faz.
 *
 * Se a geometria mudar lá, muda aqui. Não há teste amarrando as duas pontas —
 * o jeito de conferir é rodar `generate_banner` e `generate_divider_bar` e
 * medir os PNGs.
 */

/* ── Geometria, em % da altura do canvas (1920px) ────────────────────────── */

const COVER_H = 40; // 768/1920 — capa do modo "capa + banner"
const BANNER_Y = 34.219; // (768 − 222/2)/1920 — o banner é centrado na emenda
const BANNER_H = 11.5625; // 222/1920, com um título de duas linhas
const COVER_BAR_Y = 45.781; // banner_y + banner_h — a faixa encosta no banner
const BAR_H = 2.8125; // 54/1920

const CAM_H = 35; // 672/1920 — facecam do modo streamer
const STREAMER_BAR_Y = 35; // a faixa é a própria emenda entre cam e jogo
const GAME_Y = 37.8125; // 726/1920

const LEGENDA_MARGEM = 22.917; // MARGIN_V_WORD 440/1920, medido da base
const LEGENDA_MARGEM_STREAMER = 48.7; // logo abaixo da faixa, no topo do jogo

/* ── Medidas horizontais, em % da largura (1080px) ───────────────────────── */

const BANNER_PAD_X = 5.56; // 60/1080
const LEGENDA_MARGEM_X = 3.7; // MarginL/R 40/1080

/* ── Texto ───────────────────────────────────────────────────────────────── */

/** Amarelo do karaokê (`COLOR_YELLOW` em subtitler.py), não a cor da marca. */
const AMARELO = "#FFFF00";
/**
 * O título e a fala de exemplo.
 *
 * O título precisa quebrar em DUAS linhas: `BANNER_H` acima vale para um banner
 * de 222px, que é o que o render devolve nesse caso. Um título curto sai num
 * banner mais baixo e a prévia passaria a mentir sobre a altura — conferir com
 * `generate_banner` antes de trocar.
 */
const TITULO_EXEMPLO = "O que eu faria diferente se pudesse voltar";
const LEGENDA_EXEMPLO = ["eu", "não", "esperaria", "tanto", "pra", "pedir", "ajuda"];
const PALAVRA_ATIVA = 2;

interface Props {
  layout: LayoutMode;
  subtitle: SubtitleMode;
  brand: BrandDraft;
  watermarkUrl?: string;
}

export default function ClipPreview({
  layout,
  subtitle,
  brand,
  watermarkUrl,
}: Props) {
  const localUrl = useObjectUrl(brand.clipWatermark.file);
  const logo = brand.clipWatermark.remove
    ? null
    : localUrl ?? (brand.clipWatermark.saved ? watermarkUrl : null);

  const capa = layout === "cover";
  const streamer = layout === "streamer";
  // `crop` e `original` saem do vídeo como estão: sem capa, sem banner, sem
  // faixa. Desenhar camadas neles seria prometer o que o render não faz.
  const cru = !capa && !streamer;

  const barY = capa ? COVER_BAR_Y : STREAMER_BAR_Y;
  const temFaixa = (capa || streamer) && Boolean(brand.bar.name.trim());

  return (
    <div className="@container relative aspect-[9/16] w-full overflow-hidden rounded-md border border-line bg-base">
      {cru ? (
        <Placa className="absolute inset-0" tom="video" />
      ) : (
        <>
          <Placa
            className="absolute inset-x-0 top-0"
            style={{ height: `${capa ? COVER_H : CAM_H}%` }}
            tom="capa"
          />
          <Placa
            className="absolute inset-x-0 bottom-0"
            style={{ top: `${capa ? COVER_H : GAME_Y}%` }}
            tom="video"
          />
        </>
      )}

      {/* Banner de título — largura cheia, cantos vivos, caixa alta.
          Só no modo capa: no streamer ele aparece nos primeiros segundos e sai,
          então não faz parte do quadro em repouso. */}
      {capa && (
        <div
          className="absolute inset-x-0 flex items-center justify-center overflow-hidden text-center"
          style={{
            top: `${BANNER_Y}%`,
            height: `${BANNER_H}%`,
            backgroundColor: brand.banner.bg,
            paddingLeft: `${BANNER_PAD_X}%`,
            paddingRight: `${BANNER_PAD_X}%`,
          }}
        >
          <span
            className="uppercase leading-[1.08]"
            style={{
              color: brand.banner.text,
              fontFamily: fontStack(brand.banner.font).family,
              fontWeight: fontStack(brand.banner.font).weight,
              fontSize: "5.6cqw",
            }}
          >
            {TITULO_EXEMPLO}
          </span>
        </div>
      )}

      {temFaixa && (
        <FaixaDaConta
          y={barY}
          bg={brand.bar.bg}
          cor={brand.bar.text}
          fonte={brand.bar.font}
          nome={brand.bar.name}
          logo={streamer ? logo ?? null : null}
        />
      )}

      {subtitle !== "none" && (
        <Legenda
          modo={subtitle}
          margemBase={streamer ? LEGENDA_MARGEM_STREAMER : LEGENDA_MARGEM}
        />
      )}

      {/* No modo capa a logo do clipe é uma marca d'água no canto; no streamer
          ela viaja dentro da faixa (ver acima). */}
      {capa && logo && (
        // eslint-disable-next-line @next/next/no-img-element
        <img
          src={logo}
          alt=""
          className="absolute bottom-[3%] right-[4%] w-[20%] opacity-90"
        />
      )}
    </div>
  );
}

/**
 * A faixa da conta: o @ repetido de ponta a ponta, separado por pontos.
 *
 * Não é um selo centralizado — `_draw_repeating_name` desenha o nome quantas
 * vezes couber, em caixa alta, com espaçamento entre letras e um ponto no
 * meio de cada intervalo, mais um fio de luz nas duas emendas.
 */
function FaixaDaConta({
  y,
  bg,
  cor,
  fonte,
  nome,
  logo,
}: {
  y: number;
  bg: string;
  cor: string;
  fonte: string;
  nome: string;
  logo: string | null;
}) {
  const repeticoes = Array.from({ length: 9 }, (_, i) => i);
  return (
    <div
      className="absolute inset-x-0 flex items-center justify-center overflow-hidden"
      style={{
        top: `${y}%`,
        height: `${BAR_H}%`,
        backgroundColor: bg,
        // Os fios de luz das emendas (_BAR_HAIRLINE_MIX).
        boxShadow: `inset 0 1px 0 ${cor}2e, inset 0 -1px 0 ${cor}2e`,
      }}
    >
      <div
        className="flex flex-shrink-0 items-center gap-[1.4cqw] whitespace-nowrap uppercase"
        style={{
          color: cor,
          fontFamily: fontStack(fonte).family,
          fontWeight: fontStack(fonte).weight,
          fontSize: "2cqw",
          letterSpacing: "0.18em",
        }}
      >
        {repeticoes.map((i) => (
          <span key={i} className="flex items-center gap-[1.4cqw]">
            {nome}
            <span style={{ opacity: 0.45 }}>•</span>
          </span>
        ))}
      </div>
      {logo && (
        // eslint-disable-next-line @next/next/no-img-element
        <img
          src={logo}
          alt=""
          className="absolute left-[2%] top-1/2 -translate-y-1/2"
          style={{ height: "62%" }}
        />
      )}
    </div>
  );
}

/**
 * A legenda ASS, aproximada em CSS.
 *
 * Arial negrito, branca, contorno preto, ancorada pela BASE (alignment 2) a
 * `margemBase` da borda de baixo. A palavra dita fica amarela e 12% maior —
 * é o `\c&H0000FFFF&\fscx112` do karaokê, e o amarelo não muda com a marca.
 */
function Legenda({
  modo,
  margemBase,
}: {
  modo: SubtitleMode;
  margemBase: number;
}) {
  const grande = modo === "word_highlight";
  return (
    <p
      className="absolute flex flex-wrap items-end justify-center gap-x-[0.28em] gap-y-[0.1em] text-center font-bold leading-[1.15] text-white"
      style={{
        bottom: `${margemBase}%`,
        left: `${LEGENDA_MARGEM_X}%`,
        right: `${LEGENDA_MARGEM_X}%`,
        fontFamily: "Arial, Helvetica, sans-serif",
        // 84/1080 e 48/1080 — os dois tamanhos do subtitler.
        fontSize: grande ? "7.78cqw" : "4.44cqw",
        // Contorno de 5px em 1080 ≈ 0.46cqw, aproximado por sombras cruzadas.
        textShadow:
          "0 0 0.12em #000, 0.04em 0.04em 0 #000, -0.04em 0.04em 0 #000, 0.04em -0.04em 0 #000, -0.04em -0.04em 0 #000",
      }}
    >
      {grande ? (
        LEGENDA_EXEMPLO.map((palavra, i) => (
          <span
            key={i}
            style={
              i === PALAVRA_ATIVA
                ? { color: AMARELO, fontSize: "112%" }
                : undefined
            }
          >
            {palavra}
          </span>
        ))
      ) : (
        <span>{LEGENDA_EXEMPLO.join(" ")}</span>
      )}
    </p>
  );
}

function Placa({
  className = "",
  style,
  tom,
}: {
  className?: string;
  style?: React.CSSProperties;
  tom: "capa" | "video";
}) {
  return (
    <div
      aria-hidden
      className={`overflow-hidden ${className}`}
      style={{
        ...style,
        backgroundImage:
          tom === "capa"
            ? "radial-gradient(64% 78% at 50% 30%, #333f39 0%, #1d2521 60%, #121816 100%)"
            : "radial-gradient(96% 86% at 62% 78%, #1c2420 0%, #121815 62%, #0a0e0c 100%)",
      }}
    />
  );
}

/** URL temporária da imagem escolhida agora; revogada na troca. */
function useObjectUrl(file: File | null): string | null {
  const [url, setUrl] = useState<string | null>(null);
  useEffect(() => {
    if (!file) {
      setUrl(null);
      return;
    }
    const u = URL.createObjectURL(file);
    setUrl(u);
    return () => URL.revokeObjectURL(u);
  }, [file]);
  return url;
}
