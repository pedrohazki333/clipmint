"use client";

import type { JobStatus, Progresso, StageMark } from "@/lib/types";

import ProgressBar from "@/components/ProgressBar";

/**
 * O andamento do job: as etapas já fechadas, a que está rodando, e uma barra.
 *
 * ── Uma barra, e ela anda de verdade ────────────────────────────────────────
 * A primeira versão desta tela tinha uma barra por etapa com porcentagem fixa —
 * 12% durante os vinte minutos do download. A segunda trocou por uma barra
 * indeterminada e por frases que giravam num relógio: honesta, mas ainda
 * desligada do que o servidor fazia, e as frases não batiam com o passo real.
 *
 * Agora existe UMA barra, no rodapé, e o número vem do servidor: bytes
 * baixados, áudio enviado, análise em qual dos quatro passos, clipe N de M e
 * qual etapa do render daquele clipe (ver backend/app/services/progress.py). A
 * frase que aparece embaixo dela é a que o servidor mandou — não há mais lista
 * de mensagens escrita aqui, porque a tela não tem como saber o que está
 * acontecendo lá.
 *
 * O que sobrou de estimativa está isolado num lugar só e é honesto: entre dois
 * eventos reais a barra desliza rumo ao FIM DO PASSO ATUAL sem alcançá-lo (ver
 * ProgressBar). Ela nunca ultrapassa o que já se sabe e nunca anda para trás.
 *
 * O tempo de cada etapa concluída continua à vista: depois de alguns jobs dá
 * para saber que download leva ~4 min, e uma etapa travada se denuncia sozinha.
 */

const STAGES: { key: JobStatus; label: string }[] = [
  { key: "downloading", label: "Download" },
  { key: "transcribing", label: "Transcrição" },
  { key: "analyzing", label: "Análise" },
  { key: "clipping", label: "Gerando clipes" },
];

const ORDER: JobStatus[] = [
  "queued",
  "downloading",
  "transcribing",
  "analyzing",
  "clipping",
  "done",
];

interface Props {
  status: JobStatus;
  errorMessage?: string | null;
  clipsReady?: number;
  clipsTotal?: number;
  stageLog?: StageMark[] | null;
  /** Onde o servidor diz que o job está. Ausente = job terminado. */
  progresso?: Progresso | null;
}

/** Segundos → "4:12" ou "1:02:30". Sempre com dois dígitos nos minutos. */
function formatDuration(seconds: number): string {
  if (!Number.isFinite(seconds) || seconds < 0) return "";
  const h = Math.floor(seconds / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  const s = Math.floor(seconds % 60);
  const mm = String(m).padStart(h ? 2 : 1, "0");
  const ss = String(s).padStart(2, "0");
  return h ? `${h}:${mm}:${ss}` : `${mm}:${ss}`;
}

/**
 * Quanto cada etapa levou, a partir do registro de trocas.
 *
 * A duração de uma etapa é a diferença até a marca SEGUINTE — por isso o
 * registro é append-only e não precisa saber qual era a etapa anterior. A
 * última marca não tem seguinte: se o job ainda roda, ela conta até agora; se
 * terminou, até a marca terminal.
 */
function stageDurations(
  marks: StageMark[] | null | undefined,
  agora: number,
): Map<JobStatus, number> {
  const out = new Map<JobStatus, number>();
  if (!marks?.length) return out;

  for (let i = 0; i < marks.length; i++) {
    const inicio = Date.parse(marks[i].at);
    if (Number.isNaN(inicio)) continue;
    const proxima = marks[i + 1] ? Date.parse(marks[i + 1].at) : agora;
    const segundos = (proxima - inicio) / 1000;
    if (segundos < 0) continue;
    // Um job retomado passa pela mesma etapa duas vezes: soma, não substitui.
    out.set(marks[i].s, (out.get(marks[i].s) ?? 0) + segundos);
  }
  return out;
}

export default function JobStatus({
  status,
  errorMessage,
  clipsReady = 0,
  clipsTotal = 0,
  stageLog,
  progresso,
}: Props) {
  if (status === "error") {
    return (
      <div
        role="alert"
        className="rounded-md border border-danger/40 bg-danger-soft p-4"
      >
        <p className="text-body font-medium text-danger">
          O processamento parou
        </p>
        {errorMessage && (
          <p className="mt-1 text-body text-ink-dim">{errorMessage}</p>
        )}
      </div>
    );
  }

  const atual = ORDER.indexOf(status);
  const duracoes = stageDurations(stageLog, Date.now());
  const concluidas = STAGES.filter((s) => atual > ORDER.indexOf(s.key));
  const ativa = STAGES.find((s) => s.key === status);
  const emClipes = status === "clipping" && clipsTotal > 0;

  return (
    <div className="flex flex-col gap-3">
      {/* Etapas concluídas: colapsam num tique com o tempo que levaram. */}
      {concluidas.length > 0 && (
        <div className="flex flex-wrap items-center gap-x-4 gap-y-1.5">
          {concluidas.map((etapa) => {
            const segundos = duracoes.get(etapa.key);
            return (
              <span
                key={etapa.key}
                className="flex items-center gap-1.5 text-label text-ink-muted"
              >
                <svg
                  viewBox="0 0 12 12"
                  className="h-3 w-3 flex-shrink-0 text-mint"
                  aria-hidden="true"
                >
                  <path
                    d="M2.5 6.5l2.5 2.5 4.5-5"
                    fill="none"
                    stroke="currentColor"
                    strokeWidth="1.75"
                    strokeLinecap="round"
                    strokeLinejoin="round"
                  />
                </svg>
                {etapa.label}
                {segundos !== undefined && (
                  <span className="tabular text-ink-muted">
                    {formatDuration(segundos)}
                  </span>
                )}
              </span>
            );
          })}
        </div>
      )}

      {/* Etapa ativa: o único lugar com destaque. */}
      {status !== "done" && (
        <div className="flex flex-col gap-2.5 rounded-md border border-line bg-inset p-3">
          <div className="flex items-baseline justify-between gap-3">
            <span className="flex items-center gap-2 text-body font-medium text-ink">
              <span
                className="h-1.5 w-1.5 flex-shrink-0 animate-pulse rounded-full bg-running"
                aria-hidden="true"
              />
              {ativa?.label ?? "Na fila"}
            </span>
            <span className="tabular flex-shrink-0 text-label text-ink-dim">
              {emClipes && `${clipsReady} de ${clipsTotal} · `}
              {formatDuration(duracoes.get(status) ?? 0)}
            </span>
          </div>

          {/* A frase vem do servidor e muda quando o passo muda — não há
              relógio girando frases aqui. `aria-live` para quem usa leitor de
              tela acompanhar sem precisar reler a página. */}
          {progresso?.nota && (
            <p aria-live="polite" className="text-label leading-relaxed text-ink-dim">
              {progresso.nota}
            </p>
          )}

          <ProgressBar pct={progresso?.pct ?? 0} ate={progresso?.ate ?? 0} />
        </div>
      )}

      {status === "done" && (
        <p className="flex items-center gap-2 text-body text-mint">
          <svg viewBox="0 0 12 12" className="h-3.5 w-3.5" aria-hidden="true">
            <path
              d="M2.5 6.5l2.5 2.5 4.5-5"
              fill="none"
              stroke="currentColor"
              strokeWidth="1.75"
              strokeLinecap="round"
              strokeLinejoin="round"
            />
          </svg>
          Concluído
        </p>
      )}
    </div>
  );
}
