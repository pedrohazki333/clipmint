"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import Link from "next/link";

import type { VideoEnhanceJob, VideoEnhanceStatus } from "@/lib/types";
import {
  createVideoEnhance,
  deleteVideoEnhance,
  getApiErrorMessage,
  getVideoEnhanceDownloadUrl,
  getVideoEnhanceStreamUrl,
  listVideoEnhance,
} from "@/lib/api";

const ACCEPT = ".mp4,.mov,.mkv,.webm,.m4v,.avi";
const POLLING_INTERVAL = 3000; // ms — só roda enquanto houver vídeo em tratamento
const TERMINAL: VideoEnhanceStatus[] = ["done", "failed"];

const STATUS_LABEL: Record<VideoEnhanceStatus, string> = {
  pending: "na fila",
  processing: "tratando",
  done: "pronto",
  failed: "falhou",
};

const STATUS_STYLE: Record<VideoEnhanceStatus, string> = {
  pending: "bg-gray-500/10 border-gray-500/30 text-gray-400",
  processing: "bg-sky-500/10 border-sky-500/30 text-sky-400",
  done: "bg-emerald-500/10 border-emerald-500/30 text-emerald-400",
  failed: "bg-red-500/10 border-red-500/30 text-red-400",
};

function isRunning(job: VideoEnhanceJob): boolean {
  return !TERMINAL.includes(job.status);
}

export default function MelhorarVideoPage() {
  const [jobs, setJobs] = useState<VideoEnhanceJob[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const fileInputRef = useRef<HTMLInputElement>(null);

  const fetchJobs = useCallback(async () => {
    try {
      setJobs(await listVideoEnhance());
    } catch {
      // silencioso: o polling tenta de novo em segundos, e um piscar de erro
      // a cada falha de rede deixaria a tela nervosa sem motivo
    }
  }, []);

  useEffect(() => {
    fetchJobs();
  }, [fetchJobs]);

  const hasActiveWork = jobs.some(isRunning);
  useEffect(() => {
    if (!hasActiveWork) return;
    const interval = setInterval(fetchJobs, POLLING_INTERVAL);
    return () => clearInterval(interval);
  }, [hasActiveWork, fetchJobs]);

  // Envia assim que o arquivo é escolhido: não há mais nada para configurar,
  // então um botão "enviar" separado seria só um clique a mais.
  async function handleFile(file: File | null) {
    if (!file) return;
    setError("");
    setBusy(true);
    try {
      const created = await createVideoEnhance(file);
      setJobs((prev) => [created, ...prev]);
    } catch (err) {
      setError(getApiErrorMessage(err, "Erro ao enviar o vídeo. Tente novamente."));
    } finally {
      setBusy(false);
      if (fileInputRef.current) fileInputRef.current.value = "";
    }
  }

  async function handleDelete(id: string) {
    // Otimista: some da lista na hora. Se o DELETE falhar, o próximo fetch
    // traz o job de volta — melhor que travar a UI esperando o servidor.
    setJobs((prev) => prev.filter((j) => j.id !== id));
    try {
      await deleteVideoEnhance(id);
    } catch {
      fetchJobs();
    }
  }

  return (
    <div className="flex flex-col gap-8">
      <div>
        <Link href="/" className="text-sm text-gray-500 hover:text-gray-300">
          ← Suas contas
        </Link>
        <h1 className="mt-2 text-xl font-bold text-gray-100">Melhorar vídeo</h1>
        <p className="text-sm text-gray-500">
          Sobe o vídeo gerado no Gemini e ele volta em 1080p com bitrate limpo. Cada
          etapa é pulada quando o vídeo já está no alvo, então nada é reprocessado à toa.
        </p>
      </div>

      <div className="rounded-2xl border border-gray-800 bg-gray-900 p-6">
        <label
          className={`flex items-center justify-between gap-3 rounded-lg border border-dashed px-4 py-5 transition-colors ${
            busy
              ? "cursor-wait border-gray-800"
              : "cursor-pointer border-gray-700 bg-gray-800/40 hover:border-fuchsia-500/60"
          }`}
        >
          <span className="text-sm text-gray-400">
            {busy ? "Enviando..." : "Escolher vídeo (mp4, mov, webm, mkv...)"}
          </span>
          <span className="flex-shrink-0 rounded-md border border-gray-700 bg-gray-800 px-4 py-2 text-sm text-gray-200">
            Selecionar
          </span>
          <input
            ref={fileInputRef}
            type="file"
            accept={ACCEPT}
            className="hidden"
            disabled={busy}
            onChange={(e) => handleFile(e.target.files?.[0] ?? null)}
          />
        </label>

        {error && (
          <p className="mt-3 rounded bg-red-900/20 px-3 py-2 text-sm text-red-400">{error}</p>
        )}
      </div>

      <div className="flex flex-col gap-4">
        <h2 className="text-lg font-semibold text-gray-300">Vídeos tratados</h2>

        {jobs.length === 0 && (
          <p className="rounded-2xl border border-gray-800 bg-gray-900 px-6 py-8 text-center text-sm text-gray-500">
            Nenhum vídeo ainda. Envie um acima para começar.
          </p>
        )}

        {jobs.map((job) => (
          <div
            key={job.id}
            className="flex flex-col gap-4 rounded-2xl border border-gray-800 bg-gray-900 p-5"
          >
            <div className="flex items-start gap-3">
              <div className="min-w-0 flex-1">
                <div className="flex flex-wrap items-center gap-2">
                  <span
                    className={`rounded-full border px-2 py-0.5 text-xs ${STATUS_STYLE[job.status]}`}
                  >
                    {STATUS_LABEL[job.status]}
                  </span>
                  {job.status_detail && (
                    <span className="text-xs text-gray-500">{job.status_detail}…</span>
                  )}
                </div>
                <p className="mt-2 truncate text-sm text-gray-300">
                  {job.original_filename ?? "vídeo"}
                </p>

                {/* Antes → depois: o ganho medido, não prometido. */}
                {job.source_summary && (
                  <p className="mt-1 text-xs text-gray-500">
                    {job.source_summary}
                    {job.final_summary && (
                      <>
                        {" → "}
                        <span className="text-emerald-400">{job.final_summary}</span>
                      </>
                    )}
                  </p>
                )}

                {job.steps_applied.length > 0 && (
                  <p className="mt-1 text-xs text-gray-600">
                    {job.steps_applied.join(" · ")}
                  </p>
                )}
                {job.steps_skipped.length > 0 && (
                  <p className="mt-1 text-xs text-gray-700">
                    dispensado: {job.steps_skipped.join(" · ")}
                  </p>
                )}
              </div>
              <button
                onClick={() => handleDelete(job.id)}
                className="flex-shrink-0 text-xs text-gray-600 transition-colors hover:text-red-400"
                title="Excluir vídeo e arquivos"
              >
                Excluir
              </button>
            </div>

            {job.status === "failed" && job.error_message && (
              <p className="rounded bg-red-900/20 px-3 py-2 text-sm text-red-400">
                {job.error_message}
              </p>
            )}

            {/* Em 'done' a mensagem não é erro: é aviso de etapa que falhou, e o
                vídeo continua disponível logo abaixo. */}
            {job.status === "done" && job.error_message && (
              <p className="rounded bg-amber-900/20 px-3 py-2 text-xs text-amber-400">
                Vídeo entregue, mas parte do tratamento não rodou: {job.error_message}
              </p>
            )}

            {job.has_video && (
              <div className="flex flex-col gap-3">
                <video
                  src={getVideoEnhanceStreamUrl(job.id)}
                  controls
                  playsInline
                  className="max-h-[28rem] w-full rounded-lg bg-black"
                />
                <a
                  href={getVideoEnhanceDownloadUrl(job.id)}
                  className="self-start rounded-lg border border-gray-700 bg-gray-800 px-4 py-2 text-sm text-gray-200 transition-colors hover:border-fuchsia-500/60"
                >
                  Baixar vídeo
                </a>
              </div>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}
