"use client";

import { useState, useEffect, useCallback } from "react";
import { useRouter } from "next/navigation";
import type { Job, LayoutMode, Reference, SubtitleMode } from "@/lib/types";
import { createJob, listJobs, listReferences, getApiErrorMessage } from "@/lib/api";
import UrlInput from "@/components/UrlInput";
import JobCard from "@/components/JobCard";
import ReferenceForm from "@/components/ReferenceForm";
import ReferenceCard from "@/components/ReferenceCard";
import LearnedPatterns from "@/components/LearnedPatterns";
import WatermarkSettings from "@/components/WatermarkSettings";
import BannerColorSettings from "@/components/BannerColorSettings";
import BarStyleSettings from "@/components/BarStyleSettings";

const ACTIVE_POLLING_INTERVAL = 5000; // ms — só roda enquanto houver job em andamento
const TERMINAL_STATUSES = new Set(["done", "error"]);

export default function Home() {
  const router = useRouter();
  const [jobs, setJobs] = useState<Job[]>([]);
  const [references, setReferences] = useState<Reference[]>([]);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [fetchError, setFetchError] = useState("");
  const [submitError, setSubmitError] = useState("");

  const fetchJobs = useCallback(async () => {
    try {
      const data = await listJobs();
      setJobs(data);
      setFetchError("");
    } catch {
      setFetchError("Não foi possível carregar os jobs. Verifique se o backend está rodando.");
    }
  }, []);

  const fetchReferences = useCallback(async () => {
    try {
      const data = await listReferences();
      setReferences(data);
    } catch {
      // silencioso — a lista de referências é secundária
    }
  }, []);

  useEffect(() => {
    fetchJobs();
    fetchReferences();
  }, [fetchJobs, fetchReferences]);

  // Atualiza as listas automaticamente enquanto houver trabalho em andamento
  const hasActiveJobs = jobs.some((job) => !TERMINAL_STATUSES.has(job.status));
  const hasActiveReferences = references.some((r) => !TERMINAL_STATUSES.has(r.status));
  const hasActiveWork = hasActiveJobs || hasActiveReferences;
  useEffect(() => {
    if (!hasActiveWork) return;
    const interval = setInterval(() => {
      fetchJobs();
      fetchReferences();
    }, ACTIVE_POLLING_INTERVAL);
    return () => clearInterval(interval);
  }, [hasActiveWork, fetchJobs, fetchReferences]);

  async function handleSubmit(
    url: string,
    subtitleMode: SubtitleMode,
    layoutMode: LayoutMode,
  ) {
    setIsSubmitting(true);
    setSubmitError("");
    try {
      const job = await createJob({
        youtube_url: url,
        subtitle_mode: subtitleMode,
        layout_mode: layoutMode,
      });
      router.push(`/jobs/${job.id}`);
    } catch (err: unknown) {
      setSubmitError(getApiErrorMessage(err, "Erro ao criar job. Tente novamente."));
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
        {submitError && (
          <p className="mt-3 text-sm text-red-400 bg-red-900/20 rounded px-3 py-2">
            {submitError}
          </p>
        )}
      </div>

      {/* Aprender com clipe viral de outro criador */}
      <ReferenceForm />

      {references.length > 0 && (
        <div>
          <h2 className="text-lg font-semibold text-gray-300 mb-4">Referências</h2>
          <div className="flex flex-col gap-3">
            {references.map((r) => (
              <ReferenceCard key={r.id} reference={r} />
            ))}
          </div>
        </div>
      )}

      {/* Padrões aprendidos */}
      <LearnedPatterns />

      {/* Marca d'água */}
      <WatermarkSettings />

      {/* Cores do banner */}
      <BannerColorSettings />

      {/* Faixa do modo streamer */}
      <BarStyleSettings />

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
            <JobCard key={job.id} job={job} onDeleted={fetchJobs} />
          ))}
        </div>
      </div>
    </div>
  );
}
