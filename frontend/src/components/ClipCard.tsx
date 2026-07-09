"use client";

import { useState } from "react";
import type { Clip } from "@/lib/types";
import { getDownloadUrl } from "@/lib/api";
import ValidateModal from "@/components/ValidateModal";

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

const SCORE_COLOR = (score: number) => {
  if (score >= 9) return "text-emerald-400";
  if (score >= 7.5) return "text-yellow-400";
  return "text-orange-400";
};

export default function ClipCard({ clip }: Props) {
  const [modalOpen, setModalOpen] = useState(false);
  const tags = parseTags(clip.tags_json);
  const isReady = clip.status === "ready";
  const isError = clip.status === "error";

  return (
    <div className="rounded-xl bg-gray-900 border border-gray-800 p-5 flex flex-col gap-3">
      {/* Header */}
      <div className="flex items-start justify-between gap-4">
        <div className="flex-1 min-w-0">
          <p className="font-semibold text-gray-100 truncate">
            {clip.suggested_title ?? `Clip ${formatTime(clip.start_time)}–${formatTime(clip.end_time)}`}
          </p>
          {clip.part_number && (
            <span className="text-xs text-gray-500">Parte {clip.part_number}</span>
          )}
        </div>
        <div className="flex-shrink-0 text-center">
          <div className={`text-2xl font-bold ${SCORE_COLOR(clip.virality_score)}`}>
            {clip.virality_score.toFixed(1)}
          </div>
          <div className="text-xs text-gray-500">score</div>
        </div>
      </div>

      {/* Hook */}
      {clip.hook && (
        <div className="bg-gray-800 rounded-lg px-3 py-2 text-sm text-yellow-300 font-medium">
          "{clip.hook}"
        </div>
      )}

      {/* Reason */}
      {clip.reason && (
        <p className="text-sm text-gray-400 leading-relaxed">{clip.reason}</p>
      )}

      {/* Meta */}
      <div className="flex items-center gap-3 text-xs text-gray-500">
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
              className="px-2 py-0.5 rounded-full bg-gray-800 text-xs text-gray-400 border border-gray-700"
            >
              #{tag}
            </span>
          ))}
        </div>
      )}

      {/* Transcript excerpt */}
      {clip.transcript_excerpt && (
        <p className="text-xs text-gray-600 italic line-clamp-2">
          "{clip.transcript_excerpt}"
        </p>
      )}

      {/* Action */}
      {isError && (
        <div className="text-xs text-red-400 bg-red-900/20 rounded px-2 py-1">
          Falha ao processar este clip.
        </div>
      )}
      {!isReady && !isError && (
        <div className="text-xs text-gray-500 animate-pulse">Processando...</div>
      )}
      {isReady && (
        <div className="flex gap-2">
          <a
            href={getDownloadUrl(clip.id)}
            download
            className="flex-1 text-center rounded-lg bg-emerald-600 hover:bg-emerald-500 px-4 py-2 text-sm font-semibold text-white transition-colors"
          >
            Download MP4
          </a>
          <button
            onClick={() => setModalOpen(true)}
            title="Salvar como exemplo para few-shot learning"
            className="rounded-lg bg-gray-800 hover:bg-gray-700 border border-gray-700 px-3 py-2 text-sm text-gray-400 hover:text-gray-200 transition-colors"
          >
            Salvar exemplo
          </button>
        </div>
      )}

      {modalOpen && (
        <ValidateModal clipId={clip.id} onClose={() => setModalOpen(false)} />
      )}
    </div>
  );
}
