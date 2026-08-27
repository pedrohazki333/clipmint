import type { JobStatus, StageMark } from "@/lib/types";

/**
 * O andamento do job, etapa por etapa.
 *
 * A versão anterior mostrava uma barra única com porcentagem fixa por etapa —
 * 12% durante todo o download — pulsando parada por vinte minutos. Ela estimava
 * algo que ninguém sabia, e a estimativa era sempre a mesma para um vídeo de
 * três minutos e para uma live de seis horas.
 *
 * Aqui a barra só aparece onde existe uma fração de verdade: em "gerando
 * clipes" sabemos 2 de 5. Nas outras etapas mostramos o que realmente se sabe —
 * qual etapa está rodando e há quanto tempo. O tempo das etapas concluídas fica
 * à vista: depois de alguns jobs dá para saber que download leva ~4 min, e uma
 * etapa travada passa a se denunciar sozinha.
 */

const STAGES: { key: JobStatus; label: string }[] = [
  { key: "downloading", label: "Download" },
  { key: "transcribing", label: "Transcrição" },
  { key: "analyzing", label: "Análise" },
  { key: "clipping", label: "Gerando clipes" },
];

const ORDER: JobStatus[] = [
  "queued",
  "downloading",
  "transcribing",
  "analyzing",
  "clipping",
  "done",
];

interface Props {
  status: JobStatus;
  errorMessage?: string | null;
  clipsReady?: number;
  clipsTotal?: number;
  stageLog?: StageMark[] | null;
}

/** Segundos → "4:12" ou "1:02:30". Sempre com dois dígitos nos minutos. */
function formatDuration(seconds: number): string {
  if (!Number.isFinite(seconds) || seconds < 0) return "";
  const h = Math.floor(seconds / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  const s = Math.floor(seconds % 60);
  const mm = String(m).padStart(h ? 2 : 1, "0");
  const ss = String(s).padStart(2, "0");
  return h ? `${h}:${mm}:${ss}` : `${mm}:${ss}`;
}

/**
 * Quanto cada etapa levou, a partir do registro de trocas.
 *
 * A duração de uma etapa é a diferença até a marca SEGUINTE — por isso o
 * registro é append-only e não precisa saber qual era a etapa anterior. A
 * última marca não tem seguinte: se o job ainda roda, ela conta até agora; se
 * terminou, até a marca terminal.
 */
function stageDurations(
  marks: StageMark[] | null | undefined,
  agora: number,
): Map<JobStatus, number> {
  const out = new Map<JobStatus, number>();
  if (!marks?.length) return out;

  for (let i = 0; i < marks.length; i++) {
    const inicio = Date.parse(marks[i].at);
    if (Number.isNaN(inicio)) continue;
    const proxima = marks[i + 1] ? Date.parse(marks[i + 1].at) : agora;
    const segundos = (proxima - inicio) / 1000;
    if (segundos < 0) continue;
    // Um job retomado passa pela mesma etapa duas vezes: soma, não substitui.
    out.set(marks[i].s, (out.get(marks[i].s) ?? 0) + segundos);
  }
  return out;
}

export default function JobStatus({
  status,
  errorMessage,
  clipsReady = 0,
  clipsTotal = 0,
  stageLog,
}: Props) {
  if (status === "error") {
    return (
      <div
        role="alert"
        className="rounded-md border border-danger/40 bg-danger-soft p-4"
      >
        <p className="text-body font-medium text-danger">
          O processamento parou
        </p>
        {errorMessage && (
          <p className="mt-1 text-body text-ink-dim">{errorMessage}</p>
        )}
      </div>
    );
  }

  const atual = ORDER.indexOf(status);
  const duracoes = stageDurations(stageLog, Date.now());
  const concluidas = STAGES.filter((s) => atual > ORDER.indexOf(s.key));
  const ativa = STAGES.find((s) => s.key === status);
  const emClipes = status === "clipping" && clipsTotal > 0;

  return (
    <div className="flex flex-col gap-3">
      {/* Etapas concluídas: colapsam num tique com o tempo que levaram. */}
      {concluidas.length > 0 && (
        <div className="flex flex-wrap items-center gap-x-4 gap-y-1.5">
          {concluidas.map((etapa) => {
            const segundos = duracoes.get(etapa.key);
            return (
              <span
                key={etapa.key}
                className="flex items-center gap-1.5 text-label text-ink-muted"
              >
                <svg
                  viewBox="0 0 12 12"
                  className="h-3 w-3 flex-shrink-0 text-mint"
                  aria-hidden="true"
                >
                  <path
                    d="M2.5 6.5l2.5 2.5 4.5-5"
                    fill="none"
                    stroke="currentColor"
                    strokeWidth="1.75"
                    strokeLinecap="round"
                    strokeLinejoin="round"
                  />
                </svg>
                {etapa.label}
                {segundos !== undefined && (
                  <span className="tabular text-ink-muted">
                    {formatDuration(segundos)}
                  </span>
                )}
              </span>
            );
          })}
        </div>
      )}

      {/* Etapa ativa: o único lugar com destaque. */}
      {status !== "done" && (
        <div className="rounded-md border border-line bg-inset p-3">
          <div className="flex items-baseline justify-between gap-3">
            <span className="flex items-center gap-2 text-body font-medium text-ink">
              <span
                className="h-1.5 w-1.5 flex-shrink-0 animate-pulse rounded-full bg-running"
                aria-hidden="true"
              />
              {ativa?.label ?? "Na fila"}
            </span>
            <span className="tabular flex-shrink-0 text-label text-ink-dim">
              {emClipes && `${clipsReady} de ${clipsTotal} · `}
              {formatDuration(duracoes.get(status) ?? 0)}
            </span>
          </div>

          {/* Barra só onde existe uma fração de verdade. Nas outras etapas não
              sabemos quanto falta, e inventar um número foi o erro anterior. */}
          {emClipes && (
            <div
              className="mt-2.5 h-1 overflow-hidden rounded-full bg-line"
              role="progressbar"
              aria-valuenow={clipsReady}
              aria-valuemin={0}
              aria-valuemax={clipsTotal}
              aria-label="Clipes gerados"
            >
              <div
                className="h-full rounded-full bg-mint transition-[width] duration-500 ease-out"
                style={{ width: `${(clipsReady / clipsTotal) * 100}%` }}
              />
            </div>
          )}
        </div>
      )}

      {status === "done" && (
        <p className="flex items-center gap-2 text-body text-mint">
          <svg viewBox="0 0 12 12" className="h-3.5 w-3.5" aria-hidden="true">
            <path
              d="M2.5 6.5l2.5 2.5 4.5-5"
              fill="none"
              stroke="currentColor"
              strokeWidth="1.75"
              strokeLinecap="round"
              strokeLinejoin="round"
            />
          </svg>
          Concluído
        </p>
      )}
    </div>
  );
}
