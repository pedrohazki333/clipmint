"use client";

import { useState, useEffect, useCallback } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import type {
  ClipMode,
  Job,
  LayoutMode,
  ManualMode,
  SourceType,
  SubtitleMode,
} from "@/lib/types";
import { createJob, listJobs, getApiErrorMessage } from "@/lib/api";
import UrlInput from "@/components/UrlInput";
import JobCard from "@/components/JobCard";
import SchedulePanel from "@/components/SchedulePanel";
import WatermarkSettings from "@/components/WatermarkSettings";
import ClipWatermarkSettings from "@/components/ClipWatermarkSettings";
import BannerColorSettings from "@/components/BannerColorSettings";
import BarStyleSettings from "@/components/BarStyleSettings";

const ACTIVE_POLLING_INTERVAL = 5000; // ms — só roda enquanto houver job em andamento
const TERMINAL_STATUSES = new Set(["done", "error"]);

const NICHE_COPY: Record<SourceType, { title: string; blurb: string; layout: LayoutMode }> = {
  podcast: {
    title: "Podcast",
    blurb:
      "Análise por gancho verbal, arco de resolução e frase-momento. Os presets abaixo valem só para esta conta.",
    layout: "cover",
  },
  gameplay: {
    title: "Gameplay",
    blurb:
      "Análise por pico visual, reviravolta e legibilidade sem som. Os presets abaixo valem só para esta conta.",
    layout: "streamer",
  },
  siege: {
    title: "Siege X",
    blurb:
      "Análise por sequência de eliminações, abate rápido de um tiro, clutch e treta na call. Os presets abaixo valem só para esta conta.",
    layout: "streamer",
  },
};

interface Props {
  source: SourceType;
}

export default function NichePage({ source }: Props) {
  const router = useRouter();
  const copy = NICHE_COPY[source];
  const [jobs, setJobs] = useState<Job[]>([]);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [fetchError, setFetchError] = useState("");
  const [submitError, setSubmitError] = useState("");

  const fetchJobs = useCallback(async () => {
    try {
      setJobs(await listJobs(source));
      setFetchError("");
    } catch {
      setFetchError("Não foi possível carregar os jobs. Verifique se o backend está rodando.");
    }
  }, [source]);

  useEffect(() => {
    fetchJobs();
  }, [fetchJobs]);

  const hasActiveJobs = jobs.some((job) => !TERMINAL_STATUSES.has(job.status));
  useEffect(() => {
    if (!hasActiveJobs) return;
    const interval = setInterval(fetchJobs, ACTIVE_POLLING_INTERVAL);
    return () => clearInterval(interval);
  }, [hasActiveJobs, fetchJobs]);

  async function handleSubmit(
    url: string,
    subtitleMode: SubtitleMode,
    layoutMode: LayoutMode,
    _sourceType: SourceType,
    clipMode: ClipMode,
    manualClips: string,
    manualMode: ManualMode,
  ) {
    setIsSubmitting(true);
    setSubmitError("");
    try {
      // O nicho vem da página, não de um seletor: é isso que impede gerar
      // conteúdo de uma conta com a identidade da outra.
      const job = await createJob({
        youtube_url: url,
        subtitle_mode: subtitleMode,
        layout_mode: layoutMode,
        source_type: source,
        clip_mode: clipMode,
        manual_clips: manualClips.trim() || undefined,
        manual_mode: manualMode,
      });
      router.push(`/jobs/${job.id}`);
    } catch (err: unknown) {
      setSubmitError(getApiErrorMessage(err, "Erro ao criar job. Tente novamente."));
    } finally {
      setIsSubmitting(false);
    }
  }

  const readyCount = jobs.filter((j) => j.status === "done").length;

  return (
    <div className="flex flex-col gap-8">
      <div>
        <Link href="/" className="text-xs text-gray-500 hover:text-gray-300 transition-colors">
          ← Todas as contas
        </Link>
      </div>

      <div className="rounded-2xl bg-gray-900 border border-gray-800 p-6">
        <div className="flex items-center gap-3 mb-1">
          <h1 className="text-xl font-bold text-gray-100">{copy.title}</h1>
          <span className="rounded-full bg-emerald-500/10 border border-emerald-500/30 px-2.5 py-0.5 text-xs text-emerald-400">
            {jobs.length} {jobs.length === 1 ? "vídeo" : "vídeos"} · {readyCount} prontos
          </span>
        </div>
        <p className="text-sm text-gray-500 mb-6">{copy.blurb}</p>
        <UrlInput
          onSubmit={handleSubmit}
          isLoading={isSubmitting}
          lockedSource={source}
          defaultLayout={copy.layout}
        />
        {submitError && (
          <p className="mt-3 text-sm text-red-400 bg-red-900/20 rounded px-3 py-2">
            {submitError}
          </p>
        )}
      </div>

      <SchedulePanel source={source} />

      {/* Presets de marca desta conta */}
      <WatermarkSettings source={source} />
      <ClipWatermarkSettings source={source} />
      <BannerColorSettings source={source} />
      <BarStyleSettings source={source} />

      <div>
        <div className="flex items-center justify-between mb-4">
          <h2 className="text-lg font-semibold text-gray-300">
            Vídeos de {copy.title.toLowerCase()}
          </h2>
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
          <p className="text-center text-gray-600 py-12">
            Nenhum vídeo nesta conta ainda. Cole uma URL acima!
          </p>
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
