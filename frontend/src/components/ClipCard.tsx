"use client";

import { AlertTriangle, Clock3, Download, Film, Scissors } from "lucide-react";

import type { Clip } from "@/lib/types";
import { SCORE_AXES } from "@/lib/types";
import { getDownloadUrl } from "@/lib/api";
import { buttonClass } from "@/components/ui/editorial";
import { SaveExampleButton } from "@/personal";

interface Props {
  clip: Clip;
  /** Posição do clipe pela nota, entre os do job (1 = o melhor). */
  rank: number;
}

export function formatTime(seconds: number): string {
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
    const parsed = JSON.parse(tagsJson);
    return Array.isArray(parsed) ? parsed : [];
  } catch {
    return [];
  }
}

/** Faixas da nota. Verde escuro para o que é forte; âmbar para o que é bom. */
export function scoreTone(score: number): string {
  if (score >= 9) return "text-mint-ink";
  if (score >= 7.5) return "text-running";
  return "text-ink-dim";
}

function barTone(score: number): string {
  if (score >= 9) return "bg-mint-ink";
  if (score >= 7.5) return "bg-running";
  return "bg-ink-muted";
}

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
 * Um clipe: o vídeo vertical para assistir ali mesmo, e ao lado o porquê dele.
 *
 * O player usa o mesmo endereço do download. O arquivo sai do FFmpeg com
 * `+faststart`, então `preload="metadata"` busca só o começo — a página com dez
 * clipes não baixa dez vídeos para mostrar o primeiro quadro de cada um.
 */
export default function ClipCard({ clip, rank }: Props) {
  const segmentCount = countSegments(clip.segments_json);
  const tags = parseTags(clip.tags_json);
  const isReady = clip.status === "ready";
  const isError = clip.status === "error";
  // O arquivo saiu do disco pelo prazo de retenção; a análise continua aqui.
  const isExpired = clip.status === "expired";
  const titulo =
    clip.suggested_title ?? `Clipe ${formatTime(clip.start_time)}–${formatTime(clip.end_time)}`;

  return (
    <article
      aria-labelledby={`clip-${clip.id}`}
      className="grid gap-5 rounded-lg border border-line bg-raised p-4 sm:grid-cols-[13.5rem_minmax(0,1fr)] sm:p-5 lg:grid-cols-[15rem_minmax(0,1fr)]"
    >
      {/* ── O vídeo ── */}
      <div className="mx-auto w-full max-w-[17rem] sm:max-w-none">
        <div className="relative aspect-[9/16] overflow-hidden rounded-md bg-ink">
          {isReady ? (
            <video
              src={getDownloadUrl(clip.id)}
              controls
              playsInline
              preload="metadata"
              className="h-full w-full object-contain"
              aria-label={`Assistir: ${titulo}`}
            />
          ) : (
            <div className="flex h-full flex-col items-center justify-center gap-3 px-5 text-center text-label text-white/70">
              {isError ? (
                <AlertTriangle className="h-6 w-6 text-coral" aria-hidden />
              ) : isExpired ? (
                <Clock3 className="h-6 w-6" aria-hidden />
              ) : (
                <Film className="h-6 w-6 animate-pulse" aria-hidden />
              )}
              <span>
                {isError
                  ? "Não foi possível gerar este clipe"
                  : isExpired
                    ? "Arquivo apagado pelo prazo de retenção"
                    : "Gerando este clipe"}
              </span>
            </div>
          )}
          <span className="tabular pointer-events-none absolute left-2 top-2 rounded-[4px] bg-ink/80 px-1.5 py-0.5 text-[0.6875rem] text-white">
            {clip.duration.toFixed(0)}s
          </span>
        </div>
      </div>

      {/* ── O porquê ── */}
      <div className="flex min-w-0 flex-col gap-4">
        <header className="flex items-start gap-4">
          <span
            className="font-condensed text-[2.5rem] font-extrabold leading-[0.8] text-ink-muted/50"
            title={`${rank}º pela nota`}
          >
            <span className="sr-only">{rank}º pela nota: </span>
            <span aria-hidden>{String(rank).padStart(2, "0")}</span>
          </span>
          <div className="min-w-0 flex-1">
            <h3 id={`clip-${clip.id}`} className="font-display text-[1.125rem] font-bold leading-snug text-ink">
              {titulo}
            </h3>
            <p className="tabular mt-1 flex flex-wrap items-center gap-x-2 text-label text-ink-muted">
              <span>
                {formatTime(clip.start_time)} → {formatTime(clip.end_time)}
              </span>
              {clip.part_number && <span>· Parte {clip.part_number}</span>}
              {clip.file_size_bytes && <span>· {formatBytes(clip.file_size_bytes)}</span>}
            </p>
          </div>
          <div className="flex-shrink-0 text-right">
            <div className={`font-condensed text-[2.25rem] font-extrabold leading-none ${scoreTone(clip.virality_score)}`}>
              {clip.virality_score.toFixed(1)}
            </div>
            <div className="mt-0.5 text-[0.6875rem] font-semibold uppercase tracking-[0.1em] text-ink-muted">
              nota
            </div>
          </div>
        </header>

        {/* Os eixos da rubrica — é por eles que o cronograma escolhe o clipe de
            cada horário, então valem espaço na tela. */}
        {clip.hook_score !== null && (
          <dl className="grid grid-cols-2 gap-x-5 gap-y-2 sm:grid-cols-5 sm:gap-x-3">
            {SCORE_AXES.map((axis) => {
              const value = clip[axis.key];
              return (
                <div key={axis.key} title={axis.hint} className="min-w-0">
                  <div className="flex items-baseline justify-between gap-2">
                    <dt className="truncate text-[0.6875rem] font-semibold uppercase tracking-[0.06em] text-ink-muted">
                      {axis.label}
                    </dt>
                    <dd className={`tabular text-label font-semibold ${scoreTone(value ?? 0)}`}>
                      {value === null ? "–" : value.toFixed(0)}
                    </dd>
                  </div>
                  <div className="mt-1 h-1 overflow-hidden rounded-full bg-inset" aria-hidden>
                    <div
                      className={`h-full rounded-full ${barTone(value ?? 0)}`}
                      style={{ width: `${Math.max(0, Math.min(10, value ?? 0)) * 10}%` }}
                    />
                  </div>
                </div>
              );
            })}
          </dl>
        )}

        {clip.hook && (
          <blockquote className="border-l-[3px] border-coral pl-3.5 font-display text-[1.0625rem] font-semibold leading-snug text-ink">
            &ldquo;{clip.hook}&rdquo;
          </blockquote>
        )}

        {clip.reason && <p className="text-body leading-relaxed text-ink-dim">{clip.reason}</p>}

        {(segmentCount > 1 || clip.verdict === "revisar_corte") && (
          <div className="flex flex-col gap-1.5">
            {segmentCount > 1 && (
              <p className="flex items-start gap-2 text-label text-ink-dim">
                <Scissors className="mt-px h-3.5 w-3.5 flex-shrink-0" aria-hidden />
                Costurado de {segmentCount} trechos — o tempo morto entre os momentos foi removido.
              </p>
            )}
            {clip.verdict === "revisar_corte" && (
              <p className="flex items-start gap-2 text-label text-running">
                <AlertTriangle className="mt-px h-3.5 w-3.5 flex-shrink-0" aria-hidden />
                A análise sugeriu revisar o corte antes de postar.
              </p>
            )}
          </div>
        )}

        {tags.length > 0 && (
          <ul className="flex flex-wrap gap-1.5" aria-label="Hashtags sugeridas">
            {tags.map((tag) => (
              <li key={tag} className="rounded-sm bg-inset px-2 py-0.5 text-label text-ink-dim">
                #{tag}
              </li>
            ))}
          </ul>
        )}

        {clip.transcript_excerpt && (
          <p className="line-clamp-2 text-label italic text-ink-muted">
            &ldquo;{clip.transcript_excerpt}&rdquo;
          </p>
        )}

        {/* As ações ficam no pé do card, alinhadas embaixo do vídeo. */}
        <div className="mt-auto flex flex-wrap items-center gap-2 pt-1">
          {isReady && (
            <a href={getDownloadUrl(clip.id)} download className={buttonClass("primary")}>
              <Download className="h-4 w-4" aria-hidden />
              Baixar MP4
            </a>
          )}
          {isReady && SaveExampleButton && <SaveExampleButton clipId={clip.id} />}
          {isError && (
            <p className="text-label text-danger">
              Use &ldquo;Retomar de onde parou&rdquo; no topo da página para tentar de novo.
            </p>
          )}
          {isExpired && (
            <p className="text-label text-ink-dim">A análise continua salva; o vídeo, não.</p>
          )}
        </div>
      </div>
    </article>
  );
}
