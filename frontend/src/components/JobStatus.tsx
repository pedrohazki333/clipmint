import type { JobStatus } from "@/lib/types";

const STEPS: { key: JobStatus; label: string }[] = [
  { key: "downloading", label: "Download" },
  { key: "transcribing", label: "Transcrição" },
  { key: "analyzing", label: "Análise IA" },
  { key: "clipping", label: "Gerando clips" },
  { key: "done", label: "Pronto" },
];

const STEP_ORDER: JobStatus[] = [
  "queued",
  "downloading",
  "transcribing",
  "analyzing",
  "clipping",
  "done",
];

// Progresso acumulado ao ENTRAR em cada etapa (%)
const STAGE_PROGRESS: Record<JobStatus, number> = {
  queued: 3,
  downloading: 12,
  transcribing: 42,
  analyzing: 62,
  clipping: 75,
  done: 100,
  error: 0,
};

interface Props {
  status: JobStatus;
  errorMessage?: string | null;
  clipsReady?: number;
  clipsTotal?: number;
}

function computeProgress(status: JobStatus, clipsReady: number, clipsTotal: number): number {
  if (status === "done") return 100;
  if (status === "clipping" && clipsTotal > 0) {
    // 75% → 98% conforme os clips ficam prontos
    return STAGE_PROGRESS.clipping + (clipsReady / clipsTotal) * 23;
  }
  return STAGE_PROGRESS[status] ?? 0;
}

export default function JobStatus({ status, errorMessage, clipsReady = 0, clipsTotal = 0 }: Props) {
  if (status === "error") {
    return (
      <div className="rounded-lg bg-red-900/30 border border-red-800 p-4">
        <p className="text-sm font-semibold text-red-400">Pipeline falhou</p>
        {errorMessage && <p className="text-xs text-red-300 mt-1">{errorMessage}</p>}
      </div>
    );
  }

  const currentIdx = STEP_ORDER.indexOf(status);
  const progress = computeProgress(status, clipsReady, clipsTotal);
  const isRunning = status !== "done";

  return (
    <div className="flex flex-col gap-4">
      {/* Barra de progresso */}
      <div>
        <div className="flex items-center justify-between mb-1.5">
          <span className="text-xs font-medium text-gray-400">
            {status === "clipping" && clipsTotal > 0
              ? `Gerando clips (${clipsReady}/${clipsTotal})`
              : STEPS.find((s) => s.key === status)?.label ?? "Na fila"}
          </span>
          <span className="text-xs font-semibold text-emerald-400">{Math.round(progress)}%</span>
        </div>
        <div className="h-2.5 rounded-full bg-gray-800 overflow-hidden">
          <div
            className={`h-full rounded-full bg-gradient-to-r from-emerald-600 to-emerald-400 transition-[width] duration-700 ease-out ${
              isRunning ? "animate-pulse" : ""
            }`}
            style={{ width: `${progress}%` }}
          />
        </div>
      </div>

      {/* Etapas */}
      <div className="flex items-center gap-1">
        {STEPS.map((step, i) => {
          const stepIdx = STEP_ORDER.indexOf(step.key);
          const isCompleted = currentIdx > stepIdx;
          const isActive = currentIdx === stepIdx;

          return (
            <div key={step.key} className="flex items-center gap-1">
              <div className="flex flex-col items-center gap-1">
                <div
                  className={`w-3 h-3 rounded-full border-2 transition-colors ${
                    isCompleted
                      ? "bg-emerald-500 border-emerald-500"
                      : isActive
                      ? "bg-transparent border-emerald-400 animate-pulse"
                      : "bg-transparent border-gray-700"
                  }`}
                />
                <span
                  className={`text-xs ${
                    isActive ? "text-emerald-400 font-medium" : isCompleted ? "text-emerald-600" : "text-gray-600"
                  }`}
                >
                  {step.label}
                </span>
              </div>
              {i < STEPS.length - 1 && (
                <div
                  className={`w-8 h-0.5 mb-4 ${
                    currentIdx > stepIdx ? "bg-emerald-700" : "bg-gray-800"
                  }`}
                />
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}
