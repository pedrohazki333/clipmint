"use client";

import { useState, useEffect } from "react";
import { useRouter } from "next/navigation";
import type { Job, SubtitleMode } from "@/lib/types";
import { createJob, listJobs } from "@/lib/api";
import UrlInput from "@/components/UrlInput";
import JobCard from "@/components/JobCard";

export default function Home() {
  const router = useRouter();
  const [jobs, setJobs] = useState<Job[]>([]);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [fetchError, setFetchError] = useState("");

  useEffect(() => {
    fetchJobs();
  }, []);

  async function fetchJobs() {
    try {
      const data = await listJobs();
      setJobs(data);
      setFetchError("");
    } catch {
      setFetchError("Não foi possível carregar os jobs. Verifique se o backend está rodando.");
    }
  }

  async function handleSubmit(url: string, subtitleMode: SubtitleMode) {
    setIsSubmitting(true);
    try {
      const job = await createJob({ youtube_url: url, subtitle_mode: subtitleMode });
      router.push(`/jobs/${job.id}`);
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : "Erro ao criar job.";
      alert(msg);
    } finally {
      setIsSubmitting(false);
    }
  }

  return (
    <div className="flex flex-col gap-8">
      {/* Input card */}
      <div className="rounded-2xl bg-gray-900 border border-gray-800 p-6">
        <h1 className="text-xl font-bold text-gray-100 mb-1">Gerar Clips Virais</h1>
        <p className="text-sm text-gray-500 mb-6">
          Cole a URL de um vídeo do YouTube para extrair os melhores trechos automaticamente.
        </p>
        <UrlInput onSubmit={handleSubmit} isLoading={isSubmitting} />
      </div>

      {/* Jobs list */}
      <div>
        <div className="flex items-center justify-between mb-4">
          <h2 className="text-lg font-semibold text-gray-300">Jobs recentes</h2>
          <button
            onClick={fetchJobs}
            className="text-xs text-gray-500 hover:text-gray-300 transition-colors"
          >
            Atualizar
          </button>
        </div>

        {fetchError && (
          <div className="rounded-lg bg-red-900/20 border border-red-900 px-4 py-3 text-sm text-red-400 mb-4">
            {fetchError}
          </div>
        )}

        {jobs.length === 0 && !fetchError && (
          <p className="text-center text-gray-600 py-12">Nenhum job ainda. Cole uma URL acima!</p>
        )}

        <div className="flex flex-col gap-3">
          {jobs.map((job) => (
            <JobCard key={job.id} job={job} />
          ))}
        </div>
      </div>
    </div>
  );
}
