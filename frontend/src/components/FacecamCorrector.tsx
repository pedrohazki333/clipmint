"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import {
  fixFacecam,
  getApiErrorMessage,
  getFacecamReport,
  getSourceFrameUrl,
  reportFacecam,
} from "@/lib/api";
import type { Clip, FacecamRect, FacecamReport, JobDetail } from "@/lib/types";

/**
 * Corrigir o enquadramento da facecam quando a detecção erra.
 *
 * O fluxo tem uma PORTA de propósito: servir quadros de um vídeo de gigabytes e
 * re-renderizar o job custam CPU, e um botão livre viraria desperdício. Então o
 * cliente relata com print e descrição, a visão tria, e só relato aprovado
 * destrava o editor.
 *
 * Fica depois dos clipes: o problema só existe depois de olhar o resultado.
 */

const MIN = 0.05; // menor lado aceitável da caixa, em fração do quadro

function limitar(v: number, min: number, max: number): number {
  return Math.min(Math.max(v, min), max);
}

/** Mantém a caixa dentro do quadro e acima do tamanho mínimo. */
function saneada(r: FacecamRect): FacecamRect {
  const w = limitar(r.w, MIN, 1);
  const h = limitar(r.h, MIN, 1);
  return {
    x: limitar(r.x, 0, 1 - w),
    y: limitar(r.y, 0, 1 - h),
    w,
    h,
  };
}

type Alca = "mover" | "nw" | "ne" | "sw" | "se";

function EditorDeCaixa({
  jobId,
  inicio,
  fim,
  inicial,
  onPronto,
}: {
  jobId: string;
  inicio: number;
  fim: number;
  inicial: FacecamRect;
  onPronto: (rect: FacecamRect) => Promise<void>;
}) {
  const [instante, setInstante] = useState(inicio + (fim - inicio) / 2);
  const [caixa, setCaixa] = useState<FacecamRect>(saneada(inicial));
  const [salvando, setSalvando] = useState(false);
  const [erro, setErro] = useState("");
  const areaRef = useRef<HTMLDivElement>(null);
  // O arrasto em curso. Em ref, não em state: ele muda a cada pixel e um
  // re-render por movimento deixaria o arrasto travado no celular.
  const arrasto = useRef<{ alca: Alca; px: number; py: number; base: FacecamRect } | null>(null);

  function comecar(e: React.PointerEvent, alca: Alca) {
    e.preventDefault();
    e.stopPropagation();
    (e.target as HTMLElement).setPointerCapture(e.pointerId);
    arrasto.current = { alca, px: e.clientX, py: e.clientY, base: caixa };
  }

  const mover = useCallback((e: React.PointerEvent) => {
    const atual = arrasto.current;
    const area = areaRef.current;
    if (!atual || !area) return;
    const r = area.getBoundingClientRect();
    if (!r.width || !r.height) return;

    const dx = (e.clientX - atual.px) / r.width;
    const dy = (e.clientY - atual.py) / r.height;
    const b = atual.base;

    if (atual.alca === "mover") {
      setCaixa(saneada({ ...b, x: b.x + dx, y: b.y + dy }));
      return;
    }
    // Redimensionar mexe no canto arrastado e mantém o oposto parado.
    const oeste = atual.alca === "nw" || atual.alca === "sw";
    const norte = atual.alca === "nw" || atual.alca === "ne";
    const x = oeste ? b.x + dx : b.x;
    const y = norte ? b.y + dy : b.y;
    const w = oeste ? b.w - dx : b.w + dx;
    const h = norte ? b.h - dy : b.h + dy;
    if (w < MIN || h < MIN) return;
    setCaixa(saneada({ x, y, w, h }));
  }, []);

  function soltar(e: React.PointerEvent) {
    if (arrasto.current) (e.target as HTMLElement).releasePointerCapture?.(e.pointerId);
    arrasto.current = null;
  }

  async function salvar() {
    setSalvando(true);
    setErro("");
    try {
      await onPronto(caixa);
    } catch (err) {
      setErro(getApiErrorMessage(err, "Não foi possível re-renderizar."));
      setSalvando(false);
    }
  }

  const alcaClasse =
    "absolute h-6 w-6 rounded-full border-2 border-base bg-mint-strong touch-none";

  return (
    <div className="flex flex-col gap-4">
      <p className="text-body text-ink-dim">
        Arraste a caixa até ela cobrir <strong className="text-ink">só a webcam</strong>,
        sem pedaço de gameplay e sem cortar a cabeça. Use os cantos para
        redimensionar.
      </p>

      <div
        ref={areaRef}
        onPointerMove={mover}
        onPointerUp={soltar}
        onPointerCancel={soltar}
        className="relative w-full touch-none select-none overflow-hidden rounded-md border border-line bg-black"
      >
        {/* eslint-disable-next-line @next/next/no-img-element */}
        <img
          src={getSourceFrameUrl(jobId, instante)}
          alt={`Quadro do vídeo em ${instante.toFixed(1)}s`}
          className="block w-full"
          draggable={false}
        />

        <div
          onPointerDown={(e) => comecar(e, "mover")}
          className="absolute cursor-move border-2 border-mint-strong bg-mint-strong/10 touch-none"
          style={{
            left: `${caixa.x * 100}%`,
            top: `${caixa.y * 100}%`,
            width: `${caixa.w * 100}%`,
            height: `${caixa.h * 100}%`,
          }}
        >
          <span
            onPointerDown={(e) => comecar(e, "nw")}
            className={`${alcaClasse} -left-3 -top-3 cursor-nwse-resize`}
          />
          <span
            onPointerDown={(e) => comecar(e, "ne")}
            className={`${alcaClasse} -right-3 -top-3 cursor-nesw-resize`}
          />
          <span
            onPointerDown={(e) => comecar(e, "sw")}
            className={`${alcaClasse} -bottom-3 -left-3 cursor-nesw-resize`}
          />
          <span
            onPointerDown={(e) => comecar(e, "se")}
            className={`${alcaClasse} -bottom-3 -right-3 cursor-nwse-resize`}
          />
        </div>
      </div>

      {/*
        A linha do tempo varre só o trecho do clipe relatado. Não é economia: é
        onde a cam está na posição que precisa ser corrigida — no resto do vídeo
        ela pode estar em outro lugar.
      */}
      <label className="flex flex-col gap-1">
        <span className="text-label text-ink-dim">
          Instante do clipe: {instante.toFixed(1)}s
        </span>
        <input
          type="range"
          min={inicio}
          max={fim}
          step={0.5}
          value={instante}
          onChange={(e) => setInstante(Number(e.target.value))}
          className="w-full accent-mint-strong"
        />
      </label>

      {erro && (
        <p className="rounded-sm border border-danger/40 bg-danger-soft px-3 py-2 text-body text-danger">
          {erro}
        </p>
      )}

      <button
        type="button"
        onClick={salvar}
        disabled={salvando}
        className="rounded-sm bg-mint-strong px-5 py-2.5 text-body font-medium text-base transition-colors hover:bg-mint disabled:opacity-50"
      >
        {salvando ? "Re-renderizando..." : "Re-renderizar com esta caixa"}
      </button>
      <p className="text-label text-ink-muted">
        Sem custo: este vídeo já foi cobrado, e o erro foi nosso.
      </p>
    </div>
  );
}

export default function FacecamCorrector({
  job,
  clips,
  onRerender,
}: {
  job: JobDetail;
  clips: Clip[];
  onRerender: () => void;
}) {
  const [relato, setRelato] = useState<FacecamReport | null | undefined>(undefined);
  const [abrindo, setAbrindo] = useState(false);
  const [clipId, setClipId] = useState("");
  const [texto, setTexto] = useState("");
  const [arquivo, setArquivo] = useState<File | null>(null);
  const [enviando, setEnviando] = useState(false);
  const [erro, setErro] = useState("");

  const aplicavel = job.layout_mode === "streamer" && job.status === "done" && clips.length > 0;

  useEffect(() => {
    if (!aplicavel) return;
    getFacecamReport(job.id)
      .then(setRelato)
      .catch(() => setRelato(null));
  }, [aplicavel, job.id]);

  if (!aplicavel || relato === undefined) return null;

  async function enviar(e: React.FormEvent) {
    e.preventDefault();
    if (!arquivo) return;
    setEnviando(true);
    setErro("");
    try {
      setRelato(await reportFacecam(job.id, clipId || clips[0].id, texto, arquivo));
      setAbrindo(false);
    } catch (err) {
      setErro(getApiErrorMessage(err, "Não foi possível enviar o relato."));
    } finally {
      setEnviando(false);
    }
  }

  const caixa = job.facecam_rect ?? { x: 0.01, y: 0.06, w: 0.22, h: 0.25 };
  const clipeRelatado = clips.find((c) => c.id === relato?.clip_id) ?? clips[0];

  return (
    <div className="flex flex-col gap-4 rounded-md border border-line bg-raised p-4 sm:p-6">
      <h2 className="text-title font-semibold text-ink">Enquadramento da facecam</h2>

      {/* ── Aprovado: o editor ── */}
      {relato?.status === "aprovado" ? (
        <>
          <p className="text-body text-ink-dim">
            Confirmado: {relato.veredito}
          </p>
          <EditorDeCaixa
            jobId={job.id}
            inicio={relato.clip_start ?? clipeRelatado?.start_time ?? 0}
            fim={relato.clip_end ?? clipeRelatado?.end_time ?? 30}
            inicial={caixa}
            onPronto={async (rect) => {
              await fixFacecam(job.id, rect);
              onRerender();
            }}
          />
        </>
      ) : relato?.status === "recusado" ? (
        <>
          {/* Recusado precisa DIZER o que a visão viu — senão é uma parede. */}
          <p className="text-body text-ink-dim">
            Olhamos o print e o painel de cima parece correto: {relato.veredito}
          </p>
          <p className="text-body text-ink-dim">
            Se você discorda, mande outro print mostrando o trecho em que ficou
            errado — a correção só move a caixa da webcam, não muda corte, legenda
            nem cores.
          </p>
          <button
            type="button"
            onClick={() => {
              setRelato(null);
              setAbrindo(true);
            }}
            className="self-start rounded-sm border border-line px-5 py-2.5 text-body text-ink-dim transition-colors hover:border-line-strong hover:text-ink"
          >
            Mandar outro print
          </button>
        </>
      ) : abrindo ? (
        <form onSubmit={enviar} className="flex flex-col gap-3">
          <label className="flex flex-col gap-1">
            <span className="text-label text-ink-dim">Qual clipe ficou errado?</span>
            <select
              value={clipId || clips[0].id}
              onChange={(e) => setClipId(e.target.value)}
              className="rounded-sm border border-line bg-base px-3 py-2 text-body text-ink"
            >
              {clips.map((c, i) => (
                <option key={c.id} value={c.id}>
                  {i + 1}. {c.suggested_title ?? c.hook ?? `${c.start_time.toFixed(0)}s`}
                </option>
              ))}
            </select>
          </label>

          <label className="flex flex-col gap-1">
            <span className="text-label text-ink-dim">Print do enquadramento ruim</span>
            <input
              type="file"
              accept="image/png,image/jpeg,image/webp"
              onChange={(e) => setArquivo(e.target.files?.[0] ?? null)}
              required
              className="text-body text-ink-dim file:mr-3 file:rounded-sm file:border-0 file:bg-raised file:px-3 file:py-1.5 file:text-body file:text-ink"
            />
          </label>

          <label className="flex flex-col gap-1">
            <span className="text-label text-ink-dim">O que está errado?</span>
            <textarea
              value={texto}
              onChange={(e) => setTexto(e.target.value)}
              required
              rows={2}
              placeholder="Ex.: aparece um pedaço do jogo em cima e a cabeça dele fica cortada"
              className="rounded-sm border border-line bg-base px-3 py-2 text-body text-ink placeholder-ink-muted outline-none focus:border-mint"
            />
          </label>

          {erro && (
            <p className="rounded-sm border border-danger/40 bg-danger-soft px-3 py-2 text-body text-danger">
              {erro}
            </p>
          )}

          <div className="flex flex-col gap-2 sm:flex-row">
            <button
              type="submit"
              disabled={enviando || !arquivo || texto.trim().length < 5}
              className="rounded-sm bg-mint-strong px-5 py-2.5 text-body font-medium text-base transition-colors hover:bg-mint disabled:opacity-50"
            >
              {enviando ? "Analisando o print..." : "Enviar"}
            </button>
            <button
              type="button"
              onClick={() => setAbrindo(false)}
              className="rounded-sm border border-line px-5 py-2.5 text-body text-ink-dim transition-colors hover:border-line-strong hover:text-ink"
            >
              Cancelar
            </button>
          </div>
        </form>
      ) : (
        <>
          <p className="text-body text-ink-dim">
            A webcam do streamer é encontrada automaticamente. Se no seu clipe ela
            saiu com pedaço de gameplay dentro, ou cortando a cabeça, avise que a
            gente corrige e re-renderiza sem cobrar.
          </p>
          <button
            type="button"
            onClick={() => setAbrindo(true)}
            className="self-start rounded-sm border border-line px-5 py-2.5 text-body text-ink-dim transition-colors hover:border-line-strong hover:text-ink"
          >
            Problema no enquadramento da facecam
          </button>
        </>
      )}
    </div>
  );
}
