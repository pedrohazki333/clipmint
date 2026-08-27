"use client";

import type { Clip } from "@/lib/types";
import { SCORE_AXES } from "@/lib/types";
import { getDownloadUrl } from "@/lib/api";
import { SaveExampleButton } from "@/personal";

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

export default function ClipCard({ clip }: Props) {
  const segmentCount = countSegments(clip.segments_json);
  const tags = parseTags(clip.tags_json);
  const isReady = clip.status === "ready";
  const isError = clip.status === "error";
  // O arquivo saiu do disco pelo prazo de retenção; a análise continua aqui.
  const isExpired = clip.status === "expired";

  return (
    <div className="flex flex-col gap-3 rounded-md border border-line bg-raised p-5">
      {/* Header */}
      <div className="flex items-start justify-between gap-4">
        <div className="flex-1 min-w-0">
          <p className="truncate text-title font-semibold text-ink">
            {clip.suggested_title ?? `Clip ${formatTime(clip.start_time)}–${formatTime(clip.end_time)}`}
          </p>
          {clip.part_number && (
            <span className="text-label text-ink-muted">Parte {clip.part_number}</span>
          )}
        </div>
        <div className="flex-shrink-0 text-center">
          <div className={`tabular text-2xl font-semibold ${SCORE_COLOR(clip.virality_score)}`}>
            {clip.virality_score.toFixed(1)}
          </div>
          <div className="text-label text-ink-muted">nota</div>
        </div>
      </div>

      {/* Eixos da rubrica — é por eles que o cronograma escolhe o clipe de
          cada horário, então valem espaço na tela. */}
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
                <div className={`tabular text-body font-medium ${SCORE_COLOR(value ?? 0)}`}>
                  {value === null ? "–" : value.toFixed(0)}
                </div>
                <div className="text-[10px] leading-tight text-ink-muted">{axis.label}</div>
              </div>
            );
          })}
        </div>
      )}

      {segmentCount > 1 && (
        <p className="text-label text-sky-400">
          Costurado de {segmentCount} trechos — o tempo morto entre os momentos foi removido.
        </p>
      )}

      {clip.verdict === "revisar_corte" && (
        <p className="text-label text-running">
          A análise sugeriu revisar o corte antes de postar.
        </p>
      )}

      {/* Hook */}
      {clip.hook && (
        <div className="rounded-sm border-l-2 border-mint bg-inset px-3 py-2 text-body font-medium text-ink">
          "{clip.hook}"
        </div>
      )}

      {/* Reason */}
      {clip.reason && (
        <p className="text-body leading-relaxed text-ink-dim">{clip.reason}</p>
      )}

      {/* Meta */}
      <div className="tabular flex flex-wrap items-center gap-x-2 gap-y-1 text-label text-ink-muted">
        <span>{formatTime(clip.start_time)} → {formatTime(clip.end_time)}</span>
        <span>·</span>
        <span>{clip.duration.toFixed(0)}s</span>
        {clip.file_size_bytes && (
          <>
            <span>·</span>
            <span>{formatBytes(clip.file_size_bytes)}</span>
          </>
        )}
      </div>

      {/* Tags */}
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

      {/* Transcript excerpt */}
      {clip.transcript_excerpt && (
        <p className="line-clamp-2 text-label italic text-ink-muted">
          "{clip.transcript_excerpt}"
        </p>
      )}

      {/* Action */}
      {isError && (
        <div className="rounded-sm border border-danger/40 bg-danger-soft px-3 py-2 text-label text-danger">
          Este clipe não pôde ser gerado. Use &ldquo;Retomar&rdquo; no topo da página
          para tentar de novo.
        </div>
      )}
      {isExpired && (
        <div className="rounded-sm border border-line bg-inset px-3 py-2 text-label text-ink-dim">
          O arquivo deste clipe foi apagado depois do prazo de retenção. A
          análise continua salva.
        </div>
      )}
      {!isReady && !isError && !isExpired && (
        <div className="flex items-center gap-2 text-label text-ink-dim">
          <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-running" />
          Gerando este clipe
        </div>
      )}
      {isReady && (
        <div className="flex gap-2">
          <a
            href={getDownloadUrl(clip.id)}
            download
            className="flex-1 rounded-sm bg-mint-strong px-4 py-2 text-center text-body font-medium text-base transition-colors hover:bg-mint"
          >
            Download MP4
          </a>
          {SaveExampleButton && <SaveExampleButton clipId={clip.id} />}
        </div>
      )}

    </div>
  );
}
