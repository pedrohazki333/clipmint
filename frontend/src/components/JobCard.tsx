"use client";

import { useEffect, useRef, useState } from "react";
import Link from "next/link";
import type { Job } from "@/lib/types";
import { deleteJob, getApiErrorMessage } from "@/lib/api";

const STATUS_LABELS: Record<string, string> = {
  queued: "Na fila",
  downloading: "Baixando",
  transcribing: "Transcrevendo",
  analyzing: "Analisando",
  clipping: "Gerando clips",
  done: "Concluído",
  error: "Erro",
};

const STATUS_COLORS: Record<string, string> = {
  queued: "text-ink-dim",
  downloading: "text-blue-400",
  transcribing: "text-yellow-400",
  analyzing: "text-purple-400",
  clipping: "text-orange-400",
  done: "text-mint",
  error: "text-danger",
};

interface Props {
  job: Job;
  onDeleted?: () => void;
}

export default function JobCard({ job, onDeleted }: Props) {
  const label = STATUS_LABELS[job.status] ?? job.status;
  const color = STATUS_COLORS[job.status] ?? "text-ink-dim";

  const [confirming, setConfirming] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [deleteError, setDeleteError] = useState("");
  const confirmTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    return () => {
      if (confirmTimer.current) clearTimeout(confirmTimer.current);
    };
  }, []);

  async function handleDeleteClick(e: React.MouseEvent) {
    // O card inteiro é um Link — o clique no botão não pode navegar
    e.preventDefault();
    e.stopPropagation();

    if (!confirming) {
      setConfirming(true);
      confirmTimer.current = setTimeout(() => setConfirming(false), 3000);
      return;
    }

    if (confirmTimer.current) clearTimeout(confirmTimer.current);
    setDeleting(true);
    try {
      await deleteJob(job.id);
      onDeleted?.();
    } catch (err) {
      // Antes o botão simplesmente voltava ao normal: a pessoa clicava em
      // excluir, nada acontecia, e nada explicava.
      setDeleteError(
        getApiErrorMessage(err, "Não foi possível excluir este job."),
      );
      setDeleting(false);
      setConfirming(false);
    }
  }

  return (
    <Link href={`/jobs/${job.id}`}>
      <div className="group rounded-md bg-raised border border-line hover:border-line-strong p-4 transition-colors cursor-pointer">
        <div className="flex items-start gap-4">
          {job.thumbnail_url && (
            // eslint-disable-next-line @next/next/no-img-element
            <img
              src={job.thumbnail_url}
              alt={job.video_title ?? "thumbnail"}
              className="w-24 h-14 object-cover rounded-sm flex-shrink-0"
            />
          )}
          <div className="flex-1 min-w-0">
            <p className="font-medium text-ink truncate">
              {job.video_title ?? job.youtube_url}
            </p>
            {job.channel_name && (
              <p className="text-body text-ink-dim mt-0.5">{job.channel_name}</p>
            )}
            <div className="flex items-center gap-3 mt-2">
              <span className={`text-label font-semibold ${color}`}>{label}</span>
              <span className="text-label text-ink-muted">
                {new Date(job.created_at).toLocaleString("pt-BR")}
              </span>
            </div>
          </div>
          <button
            onClick={handleDeleteClick}
            disabled={deleting}
            title="Excluir job e todos os arquivos"
            className={`flex-shrink-0 rounded-sm px-3 py-1.5 text-label font-medium border transition-colors ${
              confirming
                ? "bg-red-600 border-red-500 text-white hover:bg-red-500"
                : "bg-inset border-line text-ink-dim hover:text-red-400 hover:border-red-900 opacity-0 group-hover:opacity-100"
            } ${deleting ? "opacity-50 cursor-wait" : ""}`}
          >
            {deleting ? "Excluindo..." : confirming ? "Confirmar?" : "Excluir"}
          </button>
        </div>
        {job.status === "error" && job.error_message && (
          <p className="mt-2 text-label text-danger bg-danger-soft rounded px-2 py-1 truncate">
            {job.error_message}
          </p>
        )}
        {deleteError && (
          <p className="mt-3 rounded-sm border border-danger/40 bg-danger-soft px-3 py-2 text-label text-danger">
            {deleteError}
          </p>
        )}
      </div>
    </Link>
  );
}
