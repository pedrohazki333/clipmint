"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { useParams } from "next/navigation";
import Link from "next/link";
import axios from "axios";
import { AlertTriangle, ArrowLeft, ExternalLink, Film, RotateCcw } from "lucide-react";

import type { Clip, JobDetail } from "@/lib/types";
import { getApiErrorMessage, getJob, retryJob } from "@/lib/api";
import JobStatus, { formatDuration, stageDurations } from "@/components/JobStatus";
import ClipCard from "@/components/ClipCard";
import FacecamCorrector from "@/components/FacecamCorrector";
import JobCredits from "@/components/JobCredits";
import { EstadoProjeto, duracao, quando } from "@/components/ProjectRow";
import { LAYOUT_SHORT } from "@/components/gerar/choices";
import { Eyebrow, SectionLabel, buttonClass } from "@/components/ui/editorial";
import { avisarSaldoMudou } from "@/lib/creditos";

const POLLING_INTERVAL = 2000; // ms — entre as respostas, a barra anda sozinha
const TERMINAL_STATUSES = new Set(["done", "error"]);

const LEGENDA: Record<string, string> = {
  word_highlight: "Legenda com destaque",
  traditional: "Legenda clássica",
  none: "Sem legenda",
};

type Ordem = "nota" | "video";

const voltar = (
  <Link
    href="/projetos"
    className="inline-flex items-center gap-1.5 text-body text-ink-dim transition-colors hover:text-ink"
  >
    <ArrowLeft className="h-4 w-4" aria-hidden />
    Projetos
  </Link>
);

export default function JobPage() {
  const { id } = useParams<{ id: string }>();
  const [job, setJob] = useState<JobDetail | null>(null);
  const [error, setError] = useState("");
  /** O job não existe mais — estado final, diferente de "falhou ao carregar". */
  const [gone, setGone] = useState(false);
  const [retrying, setRetrying] = useState(false);
  const [retryError, setRetryError] = useState("");
  const [semSaldo, setSemSaldo] = useState(false);
  const [ordem, setOrdem] = useState<Ordem>("nota");
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
      setError("Não foi possível carregar o projeto. Tentando de novo...");
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
      setRetryError(getApiErrorMessage(err, "Não foi possível retomar o projeto."));
    } finally {
      setRetrying(false);
    }
  }

  useEffect(() => {
    fetchJob();
    startPolling();
    return stopPolling;
  }, [id]);

  // A posição pela nota é do clipe, não da ordem escolhida: o "01" continua
  // sendo o melhor quando a lista está na ordem do vídeo.
  const ranking = useMemo(() => {
    const porNota = [...(job?.clips ?? [])].sort((a, b) => b.virality_score - a.virality_score);
    return new Map(porNota.map((c, i) => [c.id, i + 1]));
  }, [job?.clips]);

  const clipesOrdenados = useMemo<Clip[]>(() => {
    const lista = [...(job?.clips ?? [])];
    return ordem === "nota"
      ? lista.sort((a, b) => b.virality_score - a.virality_score)
      : lista.sort((a, b) => a.start_time - b.start_time);
  }, [job?.clips, ordem]);

  if (gone) {
    return (
      <div className="flex flex-col items-start gap-6">
        {voltar}
        <div className="rounded-lg border border-dashed border-line-strong px-6 py-10 sm:px-10">
          <p className="font-display text-title font-bold text-ink">Este projeto não existe mais</p>
          <p className="mt-1 text-body text-ink-dim">Ele pode ter sido excluído por aqui ou em outra aba.</p>
        </div>
      </div>
    );
  }

  if (error && !job) {
    return (
      <div className="flex flex-col items-start gap-6">
        {voltar}
        <p className="rounded-md border border-danger/30 bg-danger-soft px-4 py-3 text-body text-danger">{error}</p>
      </div>
    );
  }

  if (!job) {
    return <p className="py-20 text-center text-ink-dim animate-pulse">Carregando...</p>;
  }

  const readyClips = job.clips.filter((c) => c.status === "ready");
  const failedClips = job.clips.filter((c) => c.status === "error");
  const allClips = job.clips;
  const rodando = !TERMINAL_STATUSES.has(job.status);

  // Retomar aproveita o que já ficou pronto — vale tanto para o job que falhou
  // quanto para o que terminou com alguns clips com erro.
  const canRetry = job.status === "error" || (job.status === "done" && failedClips.length > 0);

  // O tempo de verdade, somado das etapas — nada de estimativa.
  const duracoes = stageDurations(job.stage_log, Date.now());
  const tempoTotal = [...duracoes.entries()]
    .filter(([s]) => !TERMINAL_STATUSES.has(s))
    .reduce((soma, [, seg]) => soma + seg, 0);

  const melhorNota = readyClips.length
    ? Math.max(...readyClips.map((c) => c.virality_score))
    : null;
  const dur = duracao(job.duration_seconds);

  return (
    <div className="flex flex-col gap-10">
      {/* ── Cabeçalho: o vídeo de origem ── */}
      <header className="flex flex-col gap-5">
        {voltar}
        <div className="flex flex-col gap-5 sm:flex-row sm:items-end sm:gap-7">
          <div className="relative aspect-video w-full flex-shrink-0 overflow-hidden rounded-md bg-inset sm:w-60">
            {job.thumbnail_url ? (
              // eslint-disable-next-line @next/next/no-img-element
              <img src={job.thumbnail_url} alt="" className="h-full w-full object-cover" />
            ) : (
              <div className="flex h-full items-center justify-center">
                <Film className="h-6 w-6 text-ink-muted" aria-hidden />
              </div>
            )}
            {dur && (
              <span className="tabular absolute bottom-1.5 right-1.5 rounded-[4px] bg-ink/85 px-1.5 py-0.5 text-[0.6875rem] text-white">
                {dur}
              </span>
            )}
          </div>

          <div className="min-w-0 flex-1">
            <div className="mb-3 flex flex-wrap items-center gap-3">
              <Eyebrow>Projeto</Eyebrow>
              <EstadoProjeto status={job.status} />
            </div>
            <h1 className="text-[1.75rem] font-bold leading-[1.1] text-ink sm:text-[2.25rem]">
              {job.video_title ?? "Buscando o vídeo..."}
            </h1>
            <p className="mt-3 flex flex-wrap items-center gap-x-2 gap-y-1 text-body text-ink-dim">
              {job.channel_name && <span className="font-medium text-ink">{job.channel_name}</span>}
              {job.channel_name && <span aria-hidden>·</span>}
              <span>{LAYOUT_SHORT[job.layout_mode] ?? job.layout_mode}</span>
              <span aria-hidden>·</span>
              <span>{LEGENDA[job.subtitle_mode] ?? job.subtitle_mode}</span>
              <span aria-hidden>·</span>
              <span>{quando(job.created_at)}</span>
            </p>
            <div className="mt-4 flex flex-wrap gap-x-5 gap-y-2 text-body">
              <a
                href={job.youtube_url}
                target="_blank"
                rel="noreferrer"
                className="inline-flex items-center gap-1.5 font-medium text-ink underline decoration-line-strong underline-offset-4 hover:decoration-ink"
              >
                Ver no YouTube
                <ExternalLink className="h-3.5 w-3.5" aria-hidden />
              </a>
              {job.profile_id && (
                <Link
                  href={`/perfis/${job.profile_id}`}
                  className="font-medium text-ink underline decoration-line-strong underline-offset-4 hover:decoration-ink"
                >
                  Ver o perfil usado
                </Link>
              )}
            </div>
          </div>
        </div>
      </header>

      {/* ── Processamento ── */}
      <section aria-labelledby="processamento" className="flex flex-col gap-5 rounded-lg border border-line bg-raised p-5 sm:p-6">
        <SectionLabel
          id="processamento"
          action={
            tempoTotal > 0 && (
              <span className="tabular text-label text-ink-muted">
                {rodando ? "rodando há " : job.status === "done" ? "levou " : "rodou "}
                {formatDuration(tempoTotal)}
              </span>
            )
          }
        >
          {job.status === "queued" ? "Na fila" : rodando ? "Processando" : job.status === "done" ? "Concluído" : "Parou"}
        </SectionLabel>

        <JobStatus
          status={job.status}
          clipsReady={readyClips.length}
          clipsTotal={allClips.length}
          stageLog={job.stage_log}
          progress={job.progress}
        />

        {job.status === "error" && (
          <div role="alert" className="flex gap-3 rounded-md border border-danger/30 bg-danger-soft p-4">
            <AlertTriangle className="mt-0.5 h-4 w-4 flex-shrink-0 text-danger" aria-hidden />
            <div>
              <p className="text-body font-semibold text-danger">O processamento parou</p>
              {job.error_message && <p className="mt-1 text-body text-ink-dim">{job.error_message}</p>}
            </div>
          </div>
        )}

        {canRetry && (
          <div className="flex flex-col gap-2 border-t border-line pt-5 sm:flex-row sm:items-center sm:gap-4">
            <button
              type="button"
              onClick={handleRetry}
              disabled={retrying}
              className={`${buttonClass("primary")} self-start`}
            >
              <RotateCcw className="h-4 w-4" aria-hidden />
              {retrying ? "Retomando..." : "Retomar de onde parou"}
            </button>
            <span className="text-label text-ink-dim">
              Reaproveita download, transcrição e análise
              {readyClips.length > 0 &&
                ` · ${readyClips.length} clipe${readyClips.length !== 1 ? "s" : ""} já pronto${readyClips.length !== 1 ? "s" : ""}`}
              {failedClips.length > 0 &&
                ` · refaz ${failedClips.length} clipe${failedClips.length !== 1 ? "s" : ""}`}
            </span>
          </div>
        )}
        {retryError && (
          <p className="text-label text-danger">
            {retryError}
            {semSaldo && (
              <>
                {" "}
                <Link href="/recarga" className="font-semibold underline hover:text-ink">
                  Recarregar créditos
                </Link>
              </>
            )}
          </p>
        )}

        {/* O custo fica junto do andamento: é ali que a pessoa está olhando
            enquanto espera, e é a pergunta que ela tem. */}
        <JobCredits job={job} />
      </section>

      {/* ── Clipes ── */}
      {allClips.length > 0 && (
        <section aria-labelledby="clipes" className="flex flex-col gap-5">
          <div className="flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between">
            <div>
              <SectionLabel id="clipes">Clipes</SectionLabel>
              <p className="tabular mt-2 text-body text-ink-dim">
                {readyClips.length} de {allClips.length} pronto{allClips.length !== 1 ? "s" : ""}
                {failedClips.length > 0 && ` · ${failedClips.length} com falha`}
                {melhorNota !== null && ` · melhor nota ${melhorNota.toFixed(1)}`}
              </p>
            </div>
            {allClips.length > 1 && (
              <div role="group" aria-label="Ordenar clipes" className="flex gap-1 rounded-md bg-inset p-1">
                {(
                  [
                    ["nota", "Melhor nota"],
                    ["video", "Ordem no vídeo"],
                  ] as const
                ).map(([valor, rotulo]) => (
                  <button
                    key={valor}
                    type="button"
                    onClick={() => setOrdem(valor)}
                    aria-pressed={ordem === valor}
                    className={`rounded-[7px] px-3 py-1.5 text-label font-semibold transition-colors ${
                      ordem === valor ? "bg-raised text-ink shadow-sm" : "text-ink-dim hover:text-ink"
                    }`}
                  >
                    {rotulo}
                  </button>
                ))}
              </div>
            )}
          </div>

          <div className="flex flex-col gap-4">
            {clipesOrdenados.map((clip) => (
              <ClipCard
                key={clip.id}
                clip={clip}
                rank={ranking.get(clip.id) ?? 0}
                openingHook={job.opening_hook}
              />
            ))}
          </div>
        </section>
      )}

      {/* Depois dos clipes: o problema de enquadramento só existe depois de
          olhar o resultado. */}
      <FacecamCorrector
        job={job}
        clips={allClips}
        onRerender={async () => {
          // Mesmo par do "Retomar": o job voltou para a fila, então a tela
          // precisa recarregar E voltar a acompanhar.
          await fetchJob();
          startPolling();
        }}
      />

      {rodando && allClips.length === 0 && (
        <div className="flex flex-col items-center gap-3 rounded-lg border border-dashed border-line-strong px-6 py-14 text-center">
          <Film className="h-6 w-6 animate-pulse text-ink-muted" aria-hidden />
          <p className="text-body text-ink-dim">
            Os clipes aparecem aqui assim que a análise escolher os momentos.
            <br className="hidden sm:block" /> Pode fechar esta página — o trabalho continua.
          </p>
        </div>
      )}

      {/* A causa vem do backend: um job 'done' sem clips tem mais de um motivo
          (nota abaixo do mínimo, vídeo sem fala, candidatos descartados) e a
          tela afirmava sempre o primeiro deles. */}
      {job.status === "done" && allClips.length === 0 && (
        <div className="flex flex-col items-start gap-4 rounded-lg border border-dashed border-line-strong px-6 py-10 sm:px-10">
          <div>
            <p className="font-display text-title font-bold text-ink">Nenhum clipe saiu deste vídeo</p>
            <p className="mt-1 text-body text-ink-dim">
              {job.result_note ?? "A análise não encontrou momentos fortes o bastante."}
            </p>
          </div>
          <Link href="/gerar" className={buttonClass("primary")}>
            Tentar outro vídeo
          </Link>
        </div>
      )}
    </div>
  );
}
