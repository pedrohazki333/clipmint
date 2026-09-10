"use client";

import { useState } from "react";

import type { Clip } from "@/lib/types";
import { SCORE_AXES } from "@/lib/types";
import { getDownloadUrl } from "@/lib/api";
import { SaveExampleButton } from "@/personal";
import ClipPreviewVideo from "@/components/ClipPreviewVideo";

interface Props {
  clip: Clip;
}

function formatTime(seconds: number): string {
  const m = Math.floor(seconds / 60);
  const s = Math.floor(seconds % 60);
  return `${m}:${s.toString().padStart(2, "0")}`;
}

function formatBytes(bytes: number): string {
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(0)} KB`;
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
}

function parseTags(tagsJson: string | null): string[] {
  if (!tagsJson) return [];
  try {
    return JSON.parse(tagsJson);
  } catch {
    return [];
  }
}

/** Faixas da nota. O verde é o acento do produto; o resto sinaliza atenção. */
const SCORE_COLOR = (score: number) => {
  if (score >= 9) return "text-mint";
  if (score >= 7.5) return "text-running";
  return "text-ink-dim";
};

/** Quantos trechos foram emendados neste clipe (1 = corte contínuo). */
function countSegments(segmentsJson: string | null): number {
  if (!segmentsJson) return 1;
  try {
    const parsed = JSON.parse(segmentsJson);
    return Array.isArray(parsed) ? parsed.length : 1;
  } catch {
    return 1;
  }
}

/**
 * Um clipe na lista do job.
 *
 * ── Por que a análise ficou fechada ──────────────────────────────────────────
 * O cartão mostrava, sempre abertos, cinco eixos de nota, o gancho entre aspas,
 * o parágrafo do motivo, as tags e um trecho da transcrição. Com seis clipes na
 * tela isso somava umas quarenta linhas de texto entre uma prévia e a próxima —
 * e a pergunta de quem acabou de gerar não é "por que este trecho", é "qual
 * deles eu posto". Nada saiu: tudo isso continua a um clique, atrás de "Por que
 * este clipe". Quem quer a justificativa a tem; quem quer o arquivo não precisa
 * mais rolar por cima dela.
 *
 * O que ficou de fora do fechado é o que serve para ESCOLHER: a prévia em
 * movimento, o título sugerido, a nota e a duração.
 */
export default function ClipCard({ clip }: Props) {
  const [aberto, setAberto] = useState(false);

  const segmentCount = countSegments(clip.segments_json);
  const tags = parseTags(clip.tags_json);
  const isReady = clip.status === "ready";
  const isError = clip.status === "error";
  // O arquivo saiu do disco pelo prazo de retenção; a análise continua aqui.
  const isExpired = clip.status === "expired";

  const titulo =
    clip.suggested_title ??
    `Clipe ${formatTime(clip.start_time)}–${formatTime(clip.end_time)}`;

  /** Tem alguma coisa para mostrar quando abrir? */
  const temAnalise =
    clip.hook_score !== null ||
    Boolean(clip.hook || clip.reason || clip.transcript_excerpt) ||
    tags.length > 0 ||
    segmentCount > 1 ||
    clip.verdict === "revisar_corte";

  return (
    <div className="flex flex-col rounded-md border border-line bg-raised p-3 sm:p-4">
      <div className="flex gap-3">
        {/* A prévia só existe quando o arquivo existe. */}
        <div className="w-20 flex-shrink-0 sm:w-24">
          {isReady ? (
            <ClipPreviewVideo
              clipId={clip.id}
              legenda={`${clip.duration.toFixed(0)}s`}
            />
          ) : (
            <div className="flex aspect-[9/16] w-full items-center justify-center rounded-sm border border-line bg-inset">
              {!isError && !isExpired && (
                <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-running" />
              )}
            </div>
          )}
        </div>

        <div className="flex min-w-0 flex-1 flex-col gap-2">
          <div className="flex items-start justify-between gap-3">
            <div className="min-w-0">
              <p className="line-clamp-2 text-body font-medium leading-snug text-ink">
                {titulo}
              </p>
              <p className="tabular mt-1 text-label text-ink-muted">
                {formatTime(clip.start_time)} → {formatTime(clip.end_time)}
                {clip.part_number ? ` · Parte ${clip.part_number}` : ""}
                {clip.file_size_bytes
                  ? ` · ${formatBytes(clip.file_size_bytes)}`
                  : ""}
              </p>
            </div>
            <div className="flex-shrink-0 text-center">
              <div
                className={`tabular text-title font-semibold leading-none ${SCORE_COLOR(clip.virality_score)}`}
              >
                {clip.virality_score.toFixed(1)}
              </div>
              <div className="text-[10px] leading-tight text-ink-muted">nota</div>
            </div>
          </div>

          <div>
            {isError && (
              <p className="text-label text-danger">
                Não foi possível gerar. Use &ldquo;Retomar&rdquo; no topo da
                página.
              </p>
            )}
            {isExpired && (
              <p className="text-label text-ink-dim">
                Arquivo apagado pelo prazo de retenção. A análise continua aqui.
              </p>
            )}
            {!isReady && !isError && !isExpired && (
              <p className="text-label text-ink-dim">Gerando este clipe...</p>
            )}
            {isReady && (
              <div className="flex flex-wrap gap-2">
                <a
                  href={getDownloadUrl(clip.id)}
                  download
                  className="rounded-sm bg-mint-strong px-4 py-2 text-center text-body font-medium text-on-mint transition-colors hover:bg-mint"
                >
                  Baixar MP4
                </a>
                {SaveExampleButton && <SaveExampleButton clipId={clip.id} />}
              </div>
            )}
          </div>

          {/* O gatilho da análise mora nesta coluna, e não no rodapé do cartão:
              ao lado de uma prévia de 9:16 sobra altura, e era ali que ficava o
              vão. */}
          {temAnalise && (
            <button
              type="button"
              onClick={() => setAberto((v) => !v)}
              aria-expanded={aberto}
              className="flex items-center gap-1.5 self-start text-label text-ink-dim transition-colors hover:text-ink"
            >
              Por que este clipe
              <svg
                viewBox="0 0 24 24"
                className={`h-3.5 w-3.5 transition-transform ${aberto ? "rotate-180" : ""}`}
                fill="none"
                stroke="currentColor"
                strokeWidth="2"
                strokeLinecap="round"
                strokeLinejoin="round"
                aria-hidden="true"
              >
                <path d="m6 9 6 6 6-6" />
              </svg>
            </button>
          )}
        </div>
      </div>

      {/* ── A análise, aberta: largura cheia, abaixo da prévia ─────────────── */}
      {temAnalise && (
        <>
          {aberto && (
            <div className="mt-3 flex flex-col gap-3 border-t border-line pt-3">
              {/* Eixos da rubrica — é por eles que o cronograma escolhe o clipe
                  de cada horário, então valem espaço quando a análise está à
                  vista. */}
              {clip.hook_score !== null && (
                <div className="grid grid-cols-5 gap-1">
                  {SCORE_AXES.map((axis) => {
                    const value = clip[axis.key];
                    return (
                      <div
                        key={axis.key}
                        title={axis.hint}
                        className="rounded-sm bg-inset px-1 py-1.5 text-center"
                      >
                        <div
                          className={`tabular text-body font-medium ${SCORE_COLOR(value ?? 0)}`}
                        >
                          {value === null ? "–" : value.toFixed(0)}
                        </div>
                        <div className="text-[10px] leading-tight text-ink-muted">
                          {axis.label}
                        </div>
                      </div>
                    );
                  })}
                </div>
              )}

              {clip.hook && (
                <p className="rounded-sm border-l-2 border-mint bg-inset px-3 py-2 text-body font-medium text-ink">
                  &ldquo;{clip.hook}&rdquo;
                </p>
              )}

              {clip.reason && (
                <p className="text-body leading-relaxed text-ink-dim">
                  {clip.reason}
                </p>
              )}

              {segmentCount > 1 && (
                <p className="text-label text-ink-dim">
                  Costurado de {segmentCount} trechos — o tempo morto entre os
                  momentos foi removido.
                </p>
              )}

              {clip.verdict === "revisar_corte" && (
                <p className="text-label text-running">
                  A análise sugeriu revisar o corte antes de postar.
                </p>
              )}

              {tags.length > 0 && (
                <div className="flex flex-wrap gap-1.5">
                  {tags.map((tag) => (
                    <span
                      key={tag}
                      className="rounded-full border border-line bg-inset px-2 py-0.5 text-label text-ink-dim"
                    >
                      #{tag}
                    </span>
                  ))}
                </div>
              )}

              {clip.transcript_excerpt && (
                <p className="text-label italic leading-relaxed text-ink-muted">
                  &ldquo;{clip.transcript_excerpt}&rdquo;
                </p>
              )}
            </div>
          )}
        </>
      )}
    </div>
  );
}
