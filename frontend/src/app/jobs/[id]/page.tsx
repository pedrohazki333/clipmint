"use client";

import { useEffect, useState, useRef } from "react";
import { useParams } from "next/navigation";
import Link from "next/link";
import axios from "axios";
import type { JobDetail } from "@/lib/types";
import { getApiErrorMessage, getJob, retryJob } from "@/lib/api";
import JobStatus from "@/components/JobStatus";
import ClipCard from "@/components/ClipCard";
import FixarFacecam from "@/components/FixarFacecam";
import JobCredits from "@/components/JobCredits";
import { avisarSaldoMudou } from "@/lib/creditos";

const POLLING_INTERVAL = 3000; // ms
const TERMINAL_STATUSES = new Set(["done", "error"]);

export default function JobPage() {
  const { id } = useParams<{ id: string }>();
  const [job, setJob] = useState<JobDetail | null>(null);
  const [error, setError] = useState("");
  /** O job não existe mais — estado final, diferente de "falhou ao carregar". */
  const [gone, setGone] = useState(false);
  const [retrying, setRetrying] = useState(false);
  const [retryError, setRetryError] = useState("");
  const [semSaldo, setSemSaldo] = useState(false);
  const intervalRef = useRef<ReturnType<typeof setInterval> | null>(null);

  function stopPolling() {
    if (intervalRef.current) {
      clearInterval(intervalRef.current);
      intervalRef.current = null;
    }
  }

  function startPolling() {
    if (!intervalRef.current) {
      intervalRef.current = setInterval(fetchJob, POLLING_INTERVAL);
    }
  }

  async function fetchJob() {
    try {
      const data = await getJob(id);
      setJob(data);
      setError("");
      setGone(false);

      // Para o polling quando chega em status terminal
      if (TERMINAL_STATUSES.has(data.status)) {
        stopPolling();
        // O job fechou a conta: devolveu a reserva e cobrou o real. O número no
        // topo tem que refletir isso sem a pessoa precisar recarregar a página.
        avisarSaldoMudou();
      }
    } catch (err) {
      // 404 é definitivo: o job foi excluído (daqui ou de outra aba). Continuar
      // pedindo de 3 em 3 segundos para sempre não traz ele de volta.
      if (axios.isAxiosError(err) && err.response?.status === 404) {
        stopPolling();
        setGone(true);
        return;
      }
      // Erro de rede é transitório: mantém o polling, que se recupera sozinho
      // quando o backend voltar.
      setError("Não foi possível carregar o job. Tentando de novo...");
    }
  }

  async function handleRetry() {
    setRetrying(true);
    setRetryError("");
    setSemSaldo(false);
    try {
      await retryJob(id);
      await fetchJob();
      startPolling(); // o job voltou a rodar: volta a acompanhar
    } catch (err) {
      // 402 é falta de saldo, não falha: acontece quando o job falhou, o
      // crédito foi devolvido, e retomar é receber os clips de novo. A mensagem
      // sozinha não resolve — o que a pessoa precisa é do caminho da recarga.
      setSemSaldo(axios.isAxiosError(err) && err.response?.status === 402);
      setRetryError(getApiErrorMessage(err, "Não foi possível retomar o job."));
    } finally {
      setRetrying(false);
    }
  }

  useEffect(() => {
    fetchJob();
    startPolling();
    return stopPolling;
  }, [id]);

  if (gone) {
    return (
      <div className="flex flex-col items-start gap-4">
        <div className="rounded-md bg-raised border border-line p-6">
          <p className="text-ink">Este job não existe mais.</p>
          <p className="mt-1 text-body text-ink-dim">
            Ele pode ter sido excluído por aqui ou em outra aba.
          </p>
        </div>
        <Link href="/" className="text-body text-mint hover:text-mint">
          ← Voltar para as contas
        </Link>
      </div>
    );
  }

  if (error && !job) {
    return (
      <div className="rounded-md bg-danger-soft border border-danger/40 p-6 text-danger">
        {error}
      </div>
    );
  }

  if (!job) {
    return (
      <div className="text-center py-20 text-ink-dim animate-pulse">Carregando...</div>
    );
  }

  const readyClips = job.clips.filter((c) => c.status === "ready");
  const failedClips = job.clips.filter((c) => c.status === "error");
  const allClips = job.clips;

  // Retomar aproveita o que já ficou pronto — vale tanto para o job que falhou
  // quanto para o que terminou com alguns clips com erro.
  const canRetry =
    job.status === "error" || (job.status === "done" && failedClips.length > 0);

  return (
    <div className="flex flex-col gap-8">
      {/* Voltar para o perfil que gerou este job — não para a lista de perfis.
          Job antigo (anterior aos perfis) não tem profile_id e cai na lista. */}
      <Link
        href={job.profile_id ? `/perfis/${job.profile_id}` : "/"}
        className="text-body text-ink-dim hover:text-ink transition-colors"
      >
        ← Voltar{job.profile_id ? " ao perfil" : " para os perfis"}
      </Link>

      {/* Job header */}
      <div className="flex flex-col gap-4 rounded-md border border-line bg-raised p-4 sm:p-6">
        <div className="flex flex-col gap-4 sm:flex-row sm:items-start">
          {job.thumbnail_url && (
            <img
              src={job.thumbnail_url}
              alt={job.video_title ?? "thumbnail"}
              className="h-32 w-full flex-shrink-0 rounded-sm object-cover sm:h-20 sm:w-32"
            />
          )}
          <div className="flex-1 min-w-0">
            <h1 className="text-title font-bold text-ink leading-tight">
              {job.video_title ?? "Processando..."}
            </h1>
            {job.channel_name && (
              <p className="text-body text-ink-dim mt-1">{job.channel_name}</p>
            )}
            {job.duration_seconds && (
              <p className="text-label text-ink-muted mt-1">
                {Math.floor(job.duration_seconds / 60)}:{String(Math.floor(job.duration_seconds % 60)).padStart(2, "0")} · {job.subtitle_mode}
              </p>
            )}
          </div>
        </div>

        {/* Pipeline status */}
        <div className="pt-2">
          <JobStatus
            status={job.status}
            errorMessage={job.error_message}
            clipsReady={readyClips.length}
            clipsTotal={allClips.length}
            stageLog={job.stage_log}
          />
          {/* O custo fica junto do andamento: é ali que a pessoa está olhando
              enquanto espera, e é a pergunta que ela tem. */}
          <div className="pt-2">
            <JobCredits job={job} />
          </div>
        </div>

        {job.status === "done" && (
          <p className="text-body text-mint">
            {readyClips.length} clip{readyClips.length !== 1 ? "s" : ""} pronto{readyClips.length !== 1 ? "s" : ""}
            {allClips.length > readyClips.length && ` (${allClips.length - readyClips.length} com falha)`}
          </p>
        )}

        {canRetry && (
          <div className="flex flex-col gap-2">
            <div className="flex items-center gap-3">
              <button
                onClick={handleRetry}
                disabled={retrying}
                className="rounded-sm bg-mint-strong hover:bg-mint disabled:opacity-50 disabled:cursor-not-allowed px-4 py-2 text-body font-semibold text-white transition-colors"
              >
                {retrying ? "Retomando..." : "Retomar de onde parou"}
              </button>
              <span className="text-label text-ink-dim">
                Reaproveita download, transcrição e análise
                {readyClips.length > 0 &&
                  ` · ${readyClips.length} clip${readyClips.length !== 1 ? "s" : ""} já pronto${readyClips.length !== 1 ? "s" : ""}`}
                {failedClips.length > 0 &&
                  ` · re-renderiza ${failedClips.length} clip${failedClips.length !== 1 ? "s" : ""}`}
              </span>
            </div>
            {retryError && (
              <p className="text-label text-danger">
                {retryError}
                {semSaldo && (
                  <>
                    {" "}
                    <Link href="/recarga" className="underline hover:text-ink">
                      Recarregar créditos
                    </Link>
                  </>
                )}
              </p>
            )}
          </div>
        )}
      </div>

      {/* Clips grid */}
      {allClips.length > 0 && (
        <div>
          <h2 className="text-title font-semibold text-ink mb-4">Clips gerados</h2>
          <div className="grid grid-cols-1 gap-3 md:grid-cols-2 md:gap-4">
            {[...allClips]
              .sort((a, b) => b.virality_score - a.virality_score)
              .map((clip) => (
                <ClipCard key={clip.id} clip={clip} />
              ))}
          </div>
        </div>
      )}

      {/* Depois dos clipes, nunca antes: fixar a caixa sem ter olhado o
          resultado é congelar um erro. */}
      <FixarFacecam job={job} />

      {job.status !== "done" && job.status !== "error" && allClips.length === 0 && (
        <div className="text-center py-12 text-ink-muted animate-pulse">
          Aguardando clips...
        </div>
      )}

      {/* A causa vem do backend: um job 'done' sem clips tem mais de um motivo
          (nota abaixo do mínimo, vídeo sem fala, candidatos descartados) e a
          tela afirmava sempre o primeiro deles. */}
      {job.status === "done" && allClips.length === 0 && (
        <div className="text-center py-12 text-ink-dim">
          {job.result_note ?? "Nenhum clipe foi gerado para este vídeo."}
        </div>
      )}
    </div>
  );
}
