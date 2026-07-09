"use client";

import { useEffect, useState, useRef } from "react";
import { useParams } from "next/navigation";
import Link from "next/link";
import type { JobDetail } from "@/lib/types";
import { getJob } from "@/lib/api";
import JobStatus from "@/components/JobStatus";
import ClipCard from "@/components/ClipCard";

const POLLING_INTERVAL = 3000; // ms
const TERMINAL_STATUSES = new Set(["done", "error"]);

export default function JobPage() {
  const { id } = useParams<{ id: string }>();
  const [job, setJob] = useState<JobDetail | null>(null);
  const [error, setError] = useState("");
  const intervalRef = useRef<ReturnType<typeof setInterval> | null>(null);

  async function fetchJob() {
    try {
      const data = await getJob(id);
      setJob(data);
      setError("");

      // Para o polling quando chega em status terminal
      if (TERMINAL_STATUSES.has(data.status) && intervalRef.current) {
        clearInterval(intervalRef.current);
        intervalRef.current = null;
      }
    } catch {
      setError("Não foi possível carregar o job.");
    }
  }

  useEffect(() => {
    fetchJob();
    intervalRef.current = setInterval(fetchJob, POLLING_INTERVAL);
    return () => {
      if (intervalRef.current) clearInterval(intervalRef.current);
    };
  }, [id]);

  if (error) {
    return (
      <div className="rounded-xl bg-red-900/20 border border-red-800 p-6 text-red-400">
        {error}
      </div>
    );
  }

  if (!job) {
    return (
      <div className="text-center py-20 text-gray-500 animate-pulse">Carregando...</div>
    );
  }

  const readyClips = job.clips.filter((c) => c.status === "ready");
  const allClips = job.clips;

  return (
    <div className="flex flex-col gap-8">
      {/* Back */}
      <Link href="/" className="text-sm text-gray-500 hover:text-gray-300 transition-colors">
        ← Voltar
      </Link>

      {/* Job header */}
      <div className="rounded-2xl bg-gray-900 border border-gray-800 p-6 flex flex-col gap-4">
        <div className="flex items-start gap-4">
          {job.thumbnail_url && (
            <img
              src={job.thumbnail_url}
              alt={job.video_title ?? "thumbnail"}
              className="w-32 h-20 object-cover rounded-lg flex-shrink-0"
            />
          )}
          <div className="flex-1 min-w-0">
            <h1 className="text-xl font-bold text-gray-100 leading-tight">
              {job.video_title ?? "Processando..."}
            </h1>
            {job.channel_name && (
              <p className="text-sm text-gray-500 mt-1">{job.channel_name}</p>
            )}
            {job.duration_seconds && (
              <p className="text-xs text-gray-600 mt-1">
                {Math.floor(job.duration_seconds / 60)}:{String(Math.floor(job.duration_seconds % 60)).padStart(2, "0")} · {job.subtitle_mode}
              </p>
            )}
          </div>
        </div>

        {/* Pipeline status */}
        <div className="pt-2">
          <JobStatus status={job.status} errorMessage={job.error_message} />
        </div>

        {job.status === "done" && (
          <p className="text-sm text-emerald-400">
            {readyClips.length} clip{readyClips.length !== 1 ? "s" : ""} pronto{readyClips.length !== 1 ? "s" : ""}
            {allClips.length > readyClips.length && ` (${allClips.length - readyClips.length} com falha)`}
          </p>
        )}
      </div>

      {/* Clips grid */}
      {allClips.length > 0 && (
        <div>
          <h2 className="text-lg font-semibold text-gray-300 mb-4">Clips gerados</h2>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            {allClips
              .sort((a, b) => b.virality_score - a.virality_score)
              .map((clip) => (
                <ClipCard key={clip.id} clip={clip} />
              ))}
          </div>
        </div>
      )}

      {job.status !== "done" && job.status !== "error" && allClips.length === 0 && (
        <div className="text-center py-12 text-gray-600 animate-pulse">
          Aguardando clips...
        </div>
      )}

      {job.status === "done" && allClips.length === 0 && (
        <div className="text-center py-12 text-gray-500">
          Nenhum trecho atingiu o threshold de viralidade neste vídeo.
        </div>
      )}
    </div>
  );
}
