"use client";

import { useEffect, useRef, useState, type CSSProperties } from "react";

import { FONT_STACKS, fontStack } from "@/components/FontField";
import {
  MEASURES as M,
  SIZE_FACTORS,
  WHITE,
  bandHandleColor,
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
  bloco,
}: {
  style: ClipStyle;
  size: number;
  /** Na faixa o fundo é a própria faixa; no layout A, cada linha tem a sua caixa. */
  bloco: boolean;
}) {
  const fundo = cor(style.titulo.fundo, "#0B0B0C");
  const texto = cor(style.titulo.texto, WHITE);
  const marca = cor(style.marca, "#FD375C");
  const linhas = bloco ? EXEMPLO_LINHAS_B : EXEMPLO_LINHAS_A;
  return (
    <>
      {linhas.map((linha) => (
        <div key={linha}>
          <span
            style={{
              ...titleFont(style.fonte),
              fontSize: px(size),
              color: texto,
              whiteSpace: "nowrap",
              ...(bloco
                ? {}
                : {
                    background: fundo,
                    padding: `${px(M.titlePadY)} ${px(M.titlePadX)}`,
                  }),
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
  const corLegenda = cor(style.legenda.cor, "#FD375C");

  const comContorno: CSSProperties = {
    color: WHITE,
    WebkitTextStroke: `${px(contorno * 2)} #000`,
    paintOrder: "stroke fill",
  };

  return (
    <div
      data-preview="legenda"
      style={{
        position: "absolute",
        top: px(M.captionY),
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

function Arroba({ style, faixa }: { style: ClipStyle; faixa: boolean }) {
  if (!style.arroba.ligado) return null;
  const texto = style.arroba.texto.trim() || "@suaconta";
  return (
    <div
      style={{
        ...handleFont(style.fonte),
        fontSize: px(faixa ? M.bandHandleSize : M.handleSize),
        color: faixa ? bandHandleColor(style) : WHITE,
        textShadow: faixa ? undefined : `${px(2)} ${px(2)} ${px(6)} rgba(0,0,0,.66)`,
        marginTop: px(faixa ? (style.titulo.ligado ? M.bandHandleGap : 0) : M.handleGap),
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
            <Titulo style={style} size={M.titleSize} bloco={false} />
          </div>
        )}
        <Arroba style={style} faixa={false} />
      </div>
      <Legenda style={style} layout="fullscreen" mode={mode} />
    </>
  );
}

function LayoutB({ style, mode }: { style: ClipStyle; mode: SubtitleMode }) {
  const marca = cor(style.marca, "#FD375C");
  const painel = M.bandY + M.bandH;
  return (
    <>
      <Pessoa tom="#3a4a6b" zoom={1.1} style={{ top: 0, left: 0, right: 0, height: px(M.bandY) }} />
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
        Capa: a reação mais forte do clipe
      </div>
      <Pessoa tom="#5b5247" style={{ top: px(painel), left: 0, right: 0, bottom: 0 }} />
      <div
        data-preview="faixa"
        style={{
          position: "absolute",
          top: px(M.bandY),
          left: 0,
          right: 0,
          height: px(M.bandH),
          boxSizing: "border-box",
          background: cor(style.titulo.fundo, "#0B0B0C"),
          borderTop: `${px(M.bandBorder)} solid ${marca}`,
          borderBottom: `${px(M.bandBorder)} solid ${marca}`,
          display: "flex",
          flexDirection: "column",
          justifyContent: "center",
          paddingLeft: px(M.titleX),
          paddingRight: px(M.canvasW - M.titleMaxRight),
        }}
      >
        {style.titulo.ligado && (
          <div style={{ lineHeight: M.bandLineHeight }}>
            <Titulo style={style} size={M.bandTitleSize} bloco />
          </div>
        )}
        <Arroba style={style} faixa />
      </div>
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
}: {
  style: ClipStyle;
  layout: LayoutMode;
  mode: SubtitleMode;
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
      >
        {layout === "fullscreen" ? (
          <LayoutA style={style} mode={mode} />
        ) : layout === "cover" ? (
          <LayoutB style={style} mode={mode} />
        ) : (
          <LayoutSimples style={style} layout={layout} mode={mode} />
        )}
      </div>
    </div>
  );
}
