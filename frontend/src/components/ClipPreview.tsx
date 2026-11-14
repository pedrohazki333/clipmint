"use client";

import {
  useEffect,
  useRef,
  useState,
  type CSSProperties,
  type PointerEvent as ReactPointerEvent,
} from "react";

import { FONT_STACKS, fontStack } from "@/components/FontField";
import {
  DEFAULT_BRAND,
  MEASURES as M,
  SIZE_FACTORS,
  WHITE,
  captionHeightApplies,
  clampCaptionY,
  watermarkFor,
  isHex,
  type ClipStyle,
} from "@/lib/clipStyle";
import type { LayoutMode, SubtitleMode } from "@/lib/types";

/**
 * A prévia do clipe, ao vivo, em CSS.
 *
 * As medidas são as do render, em escala 0,375 (405x720), e por isso mudar uma cor aqui
 * responde na hora sem renderizar nada. É uma prévia de VISUAL: o rosto é um desenho, e
 * o texto é um exemplo.
 */

const S = M.previewScale;
const px = (value: number) => `${value * S}px`;

// Quebradas à mão como o render as quebra: em linhas equilibradas. Deixar o navegador
// quebrar mostraria uma palavra sozinha na última linha, o que o clipe nunca tem.
const EXEMPLO_LINHAS_A = ["PERDI 200 MIL", "SEGUIDORES", "NUMA NOITE"];
const EXEMPLO_LINHAS_B = ["PERDI 200 MIL", "SEGUIDORES NUMA NOITE"];
const EXEMPLO_PALAVRA_CHAVE = "200";
const EXEMPLO_LEGENDA = ["eu", "perdi", "tudo"];
const EXEMPLO_ATIVA = 1;

/** Cor segura para pintar enquanto a pessoa ainda está digitando um hexadecimal. */
const cor = (value: string, fallback: string) => (isHex(value) ? value : fallback);

function titleFont(fonte: string): CSSProperties {
  if (fonte === "archivo") {
    return {
      fontFamily: "var(--font-archivo), sans-serif",
      fontWeight: 900,
      fontStretch: "75%",
    };
  }
  const { family } = fontStack(fonte);
  return { fontFamily: family, fontWeight: 700 };
}

function captionFont(fonte: string): CSSProperties {
  if (fonte === "archivo") {
    return {
      fontFamily: "var(--font-archivo), sans-serif",
      fontWeight: 800,
      fontStretch: "92%",
    };
  }
  return { fontFamily: fontStack(fonte).family, fontWeight: FONT_STACKS[fonte]?.weight ?? 700 };
}

function handleFont(fonte: string): CSSProperties {
  if (fonte === "archivo") {
    return { fontFamily: "var(--font-archivo), sans-serif", fontWeight: 700 };
  }
  return { fontFamily: fontStack(fonte).family, fontWeight: 700 };
}

/** Quem fala, desenhado: o que importa aqui é o que fica por cima. */
function Pessoa({ tom, zoom = 1, style }: { tom: string; zoom?: number; style?: CSSProperties }) {
  return (
    <div
      aria-hidden
      style={{
        position: "absolute",
        overflow: "hidden",
        background: `linear-gradient(180deg, ${tom} 0%, #17181c 100%)`,
        ...style,
      }}
    >
      <svg viewBox="0 0 100 100" preserveAspectRatio="xMidYMax slice" style={{ width: "100%", height: "100%" }}>
        <g transform={`translate(50 100) scale(${zoom}) translate(-50 -100)`} fill="#0d0e11" opacity="0.8">
          <circle cx="50" cy="44" r="17" />
          <path d="M16 100c0-22 15-34 34-34s34 12 34 34z" />
        </g>
      </svg>
    </div>
  );
}

function Titulo({
  style,
  size,
}: {
  style: ClipStyle;
  size: number;
}) {
  const fundo = cor(style.titulo.fundo, "#0B0B0C");
  const texto = cor(style.titulo.texto, WHITE);
  const marca = cor(style.marca, DEFAULT_BRAND);
  return (
    <>
      {EXEMPLO_LINHAS_A.map((linha) => (
        <div key={linha}>
          <span
            style={{
              ...titleFont(style.fonte),
              fontSize: px(size),
              color: texto,
              whiteSpace: "nowrap",
              background: fundo,
              padding: `${px(M.titlePadY)} ${px(M.titlePadX)}`,
            }}
          >
            {linha.split(" ").map((palavra, i, todas) => (
              <span
                key={i}
                style={palavra === EXEMPLO_PALAVRA_CHAVE ? { color: marca } : undefined}
              >
                {palavra}
                {i < todas.length - 1 ? " " : ""}
              </span>
            ))}
          </span>
        </div>
      ))}
    </>
  );
}

function Legenda({
  style,
  layout,
  mode,
}: {
  style: ClipStyle;
  layout: LayoutMode;
  mode: SubtitleMode;
}) {
  if (mode === "none") return null;
  const capa = layout === "cover";
  const fator = SIZE_FACTORS[style.legenda.tamanho];
  const size = (capa ? M.captionSizeCover : M.captionSizeFullscreen) * fator;
  const contorno = capa ? M.captionOutlineCover : M.captionOutlineFullscreen;
  const destaque = mode === "word_highlight";
  const caixa = destaque && style.legenda.estilo === "caixa";
  const corLegenda = cor(style.legenda.cor, DEFAULT_BRAND);

  const comContorno: CSSProperties = {
    color: WHITE,
    WebkitTextStroke: `${px(contorno * 2)} #000`,
    paintOrder: "stroke fill",
  };

  const centro = captionHeightApplies(layout) ? (style.legenda.altura ?? M.captionY) : M.captionY;
  return (
    <div
      data-preview="legenda"
      style={{
        position: "absolute",
        zIndex: 2,
        top: px(centro),
        left: 0,
        right: 0,
        transform: "translateY(-50%)",
        display: "flex",
        justifyContent: "center",
        alignItems: "center",
        gap: caixa ? px(M.boxPaddingX + M.boxNeighborGap) : px(size * 0.24),
        ...captionFont(style.fonte),
        fontSize: px(size),
        lineHeight: 1.09,
        whiteSpace: "nowrap",
      }}
    >
      {EXEMPLO_LEGENDA.map((palavra, i) => {
        if (destaque && i === EXEMPLO_ATIVA) {
          return caixa ? (
            <span
              key={i}
              data-preview="caixa"
              style={{
                background: corLegenda,
                color: "#0B0B0C",
                padding: `0 ${px(M.boxPaddingX)}`,
                margin: `0 -${px(M.boxPaddingX)}`,
                borderRadius: px(M.boxRadius),
              }}
            >
              {palavra}
            </span>
          ) : (
            <span key={i} style={{ ...comContorno, color: corLegenda }}>
              {palavra}
            </span>
          );
        }
        return (
          <span key={i} style={comContorno}>
            {palavra}
          </span>
        );
      })}
    </div>
  );
}

function Arroba({ style }: { style: ClipStyle }) {
  if (!style.arroba.ligado) return null;
  const texto = style.arroba.texto.trim() || "@suaconta";
  return (
    <div
      style={{
        ...handleFont(style.fonte),
        fontSize: px(M.handleSize),
        color: WHITE,
        textShadow: `${px(2)} ${px(2)} ${px(6)} rgba(0,0,0,.66)`,
        marginTop: px(M.handleGap),
        whiteSpace: "nowrap",
      }}
    >
      {texto}
    </div>
  );
}

function LayoutA({ style, mode }: { style: ClipStyle; mode: SubtitleMode }) {
  return (
    <>
      <Pessoa tom="#5b5247" zoom={0.9} style={{ inset: 0 }} />
      <div
        data-preview="titulo"
        style={{
          position: "absolute",
          left: px(M.titleX),
          top: px(M.titleY),
          width: px(M.titleMaxRight - M.titleX),
        }}
      >
        {style.titulo.ligado && (
          <div style={{ lineHeight: M.titleLineHeight }}>
            <Titulo style={style} size={M.titleSize} />
          </div>
        )}
        <Arroba style={style} />
      </div>
      <Legenda style={style} layout="fullscreen" mode={mode} />
    </>
  );
}

/** O nome da faixa, repetido de ponta a ponta como o render escreve. */
function FaixaDoArroba({ style, top }: { style: ClipStyle; top: number }) {
  const fundo = cor(style.titulo.fundo, "#0B0B0C");
  const marca = cor(style.marca, DEFAULT_BRAND);
  const nome = style.arroba.texto.trim().toUpperCase();
  const tamanho = Math.floor(M.barH * M.barTextFrac);
  const fio = `color-mix(in srgb, ${marca} 18%, ${fundo})`;
  return (
    <div
      data-preview="faixa"
      style={{
        position: "absolute",
        top: px(top),
        left: 0,
        right: 0,
        height: px(M.barH),
        boxSizing: "border-box",
        background: fundo,
        borderTop: `1px solid ${fio}`,
        borderBottom: `1px solid ${fio}`,
        overflow: "hidden",
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        whiteSpace: "nowrap",
        ...titleFont(style.fonte),
        fontSize: px(tamanho),
        letterSpacing: `${M.barTracking}em`,
        color: marca,
      }}
    >
      {Array.from({ length: 7 }, (_, i) => (
        <span key={i} style={{ display: "inline-flex", alignItems: "center", flexShrink: 0 }}>
          {i > 0 && (
            <span
              style={{
                color: `color-mix(in srgb, ${marca} 45%, ${fundo})`,
                margin: `0 ${px((tamanho * M.barGap) / 2)}`,
              }}
            >
              •
            </span>
          )}
          {nome}
        </span>
      ))}
    </div>
  );
}

function LayoutB({ style, mode }: { style: ClipStyle; mode: SubtitleMode }) {
  const linhas = style.titulo.ligado ? EXEMPLO_LINHAS_B : [];
  const linhaH = M.bannerTitleSize * M.bannerLineHeight;
  const bannerH = linhas.length ? linhas.length * linhaH + 2 * M.bannerPadY : 0;
  const bannerY = M.coverH - bannerH / 2;
  const temArroba = style.arroba.ligado && style.arroba.texto.trim() !== "";
  return (
    <>
      <Pessoa tom="#3a4a6b" zoom={1.1} style={{ top: 0, left: 0, right: 0, height: px(M.coverH) }} />
      <div
        data-preview="capa-rotulo"
        style={{
          position: "absolute",
          top: px(30),
          left: px(30),
          padding: "2px 6px",
          borderRadius: 3,
          background: "rgba(0,0,0,.55)",
          color: "#fff",
          fontSize: 10,
        }}
      >
        Capa: o rosto mais expressivo do clipe
      </div>
      <Pessoa tom="#5b5247" style={{ top: px(M.coverH), left: 0, right: 0, bottom: 0 }} />
      {linhas.length > 0 && (
        <div
          data-preview="banner"
          style={{
            position: "absolute",
            top: px(bannerY),
            left: 0,
            right: 0,
            height: px(bannerH),
            background: cor(style.titulo.fundo, "#0B0B0C"),
            color: cor(style.titulo.texto, WHITE),
            display: "flex",
            flexDirection: "column",
            justifyContent: "center",
            alignItems: "center",
            ...titleFont(style.fonte),
            fontSize: px(M.bannerTitleSize),
            lineHeight: px(linhaH),
            whiteSpace: "nowrap",
          }}
        >
          {linhas.map((linha) => (
            <div key={linha}>{linha}</div>
          ))}
        </div>
      )}
      {temArroba && <FaixaDoArroba style={style} top={linhas.length ? bannerY + bannerH : M.coverH} />}
      <Legenda style={style} layout="cover" mode={mode} />
    </>
  );
}

function LayoutSimples({
  style,
  layout,
  mode,
}: {
  style: ClipStyle;
  layout: LayoutMode;
  mode: SubtitleMode;
}) {
  if (layout === "streamer") {
    return (
      <>
        <Pessoa tom="#5b5247" zoom={1.2} style={{ top: 0, left: 0, right: 0, height: "35%" }} />
        <div
          aria-hidden
          style={{
            position: "absolute",
            top: "37.9%",
            left: 0,
            right: 0,
            bottom: 0,
            background: "linear-gradient(135deg,#1f3a2e,#14151a 70%)",
          }}
        />
        <Legenda style={style} layout={layout} mode={mode} />
      </>
    );
  }
  if (layout === "original") {
    return (
      <>
        <Pessoa tom="#5b5247" style={{ top: "34%", left: 0, right: 0, height: "32%" }} />
        <Legenda style={style} layout={layout} mode={mode} />
      </>
    );
  }
  return (
    <>
      <Pessoa tom="#5b5247" zoom={0.9} style={{ inset: 0 }} />
      <Legenda style={style} layout={layout} mode={mode} />
    </>
  );
}

export default function ClipPreview({
  style,
  layout,
  mode,
  onMoverLegenda,
  watermarkUrl,
  onMoverMarca,
}: {
  style: ClipStyle;
  layout: LayoutMode;
  mode: SubtitleMode;
  /** Com ele, a legenda pode ser arrastada na prévia para cima e para baixo. */
  onMoverLegenda?: (altura: number) => void;
  /** A arte da conta. Sem ela (ou desligada neste layout), a prévia não mostra marca. */
  watermarkUrl?: string | null;
  /** Com ele, a arte pode ser arrastada para qualquer lugar do quadro. */
  onMoverMarca?: (x: number, y: number) => void;
}) {
  const largura = M.canvasW * S;
  const altura = M.canvasH * S;
  const moldura = useRef<HTMLDivElement>(null);
  const [fator, setFator] = useState(1);

  // Numa tela mais estreita que 405px o quadro encolhe inteiro, e não só na largura:
  // limitar a largura cortava o que está à direita e deformava a proporção.
  useEffect(() => {
    const elemento = moldura.current;
    if (!elemento) return;
    const medir = () => setFator(Math.min(1, elemento.clientWidth / largura));
    medir();
    const observador = new ResizeObserver(medir);
    observador.observe(elemento);
    return () => observador.disconnect();
  }, [largura]);

  // O que está sendo arrastado e, na marca, onde o dedo pegou nela: sem essa folga o
  // centro da arte pularia para baixo do cursor no primeiro movimento.
  const arrastando = useRef<{ alvo: "legenda" | "marca"; dx: number; dy: number } | null>(null);
  const legendaArrastavel =
    Boolean(onMoverLegenda) && mode !== "none" && captionHeightApplies(layout);
  const marca = watermarkFor(style, layout);
  const [arteFalhou, setArteFalhou] = useState(false);
  useEffect(() => setArteFalhou(false), [watermarkUrl]);
  const mostraMarca = Boolean(watermarkUrl) && marca.ligado && !arteFalhou;
  const marcaArrastavel = mostraMarca && Boolean(onMoverMarca);

  // A posição sai do retângulo na tela, que já inclui a escala do quadro.
  function fracao(e: ReactPointerEvent<HTMLDivElement>): { fx: number; fy: number } {
    const caixa = e.currentTarget.getBoundingClientRect();
    return {
      fx: (e.clientX - caixa.left) / caixa.width,
      fy: (e.clientY - caixa.top) / caixa.height,
    };
  }

  function comecar(e: ReactPointerEvent<HTMLDivElement>) {
    const alvo = e.target as HTMLElement;
    const { fx, fy } = fracao(e);
    if (marcaArrastavel && alvo.closest('[data-preview="marca"]')) {
      arrastando.current = { alvo: "marca", dx: fx - marca.x, dy: fy - marca.y };
    } else if (legendaArrastavel && alvo.closest('[data-preview="legenda"]')) {
      arrastando.current = { alvo: "legenda", dx: 0, dy: 0 };
    } else {
      return;
    }
    e.currentTarget.setPointerCapture(e.pointerId);
    e.preventDefault();
  }

  function mover(e: ReactPointerEvent<HTMLDivElement>) {
    const atual = arrastando.current;
    if (!atual) return;
    const { fx, fy } = fracao(e);
    if (atual.alvo === "legenda") {
      onMoverLegenda?.(clampCaptionY(fy * M.canvasH));
    } else {
      const limita = (v: number) => Math.round(Math.min(1, Math.max(0, v)) * 1000) / 1000;
      onMoverMarca?.(limita(fx - atual.dx), limita(fy - atual.dy));
    }
  }

  function soltar(e: ReactPointerEvent<HTMLDivElement>) {
    if (!arrastando.current) return;
    arrastando.current = null;
    e.currentTarget.releasePointerCapture(e.pointerId);
  }

  return (
    <div ref={moldura} style={{ width: "100%", maxWidth: largura, height: altura * fator }}>
      <div
        data-preview="quadro"
        role="img"
        aria-label="Prévia do visual do clipe"
        style={{
          position: "relative",
          width: largura,
          height: altura,
          overflow: "hidden",
          background: "#000",
          transform: `scale(${fator})`,
          transformOrigin: "top left",
        }}
        data-arrastavel={
          [legendaArrastavel && "legenda", marcaArrastavel && "marca"].filter(Boolean).join(" ") ||
          undefined
        }
        onPointerDown={comecar}
        onPointerMove={mover}
        onPointerUp={soltar}
        onPointerCancel={soltar}
      >
        {layout === "fullscreen" ? (
          <LayoutA style={style} mode={mode} />
        ) : layout === "cover" ? (
          <LayoutB style={style} mode={mode} />
        ) : (
          <LayoutSimples style={style} layout={layout} mode={mode} />
        )}
        {mostraMarca && (
          // A arte por cima do título e por baixo da legenda, como o render a assenta.
          // eslint-disable-next-line @next/next/no-img-element
          <img
            src={watermarkUrl!}
            alt=""
            data-preview="marca"
            draggable={false}
            onError={() => setArteFalhou(true)}
            style={{
              position: "absolute",
              zIndex: 1,
              left: px(marca.x * M.canvasW),
              top: px(marca.y * M.canvasH),
              width: px(marca.largura * M.canvasW),
              height: "auto",
              transform: "translate(-50%, -50%)",
              opacity: marca.opacidade,
              userSelect: "none",
            }}
          />
        )}
      </div>
    </div>
  );
}
