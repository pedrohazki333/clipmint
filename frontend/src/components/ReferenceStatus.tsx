import type { ReferenceStatus } from "@/lib/types";

const STEPS: { key: ReferenceStatus; label: string }[] = [
  { key: "downloading_source", label: "Baixando" },
  { key: "transcribing", label: "Transcrição" },
  { key: "aligning", label: "Localizando" },
  { key: "analyzing", label: "Análise IA" },
  { key: "done", label: "Pronto" },
];

const STEP_ORDER: ReferenceStatus[] = [
  "queued",
  "downloading_source",
  "transcribing",
  "aligning",
  "analyzing",
  "done",
];

const STAGE_PROGRESS: Record<ReferenceStatus, number> = {
  queued: 4,
  downloading_source: 15,
  transcribing: 45,
  aligning: 68,
  analyzing: 82,
  done: 100,
  error: 0,
};

interface Props {
  status: ReferenceStatus;
  errorMessage?: string | null;
}

export default function ReferenceStatus({ status, errorMessage }: Props) {
  if (status === "error") {
    return (
      <div className="rounded-lg bg-red-900/30 border border-red-800 p-4">
        <p className="text-sm font-semibold text-red-400">Falha ao processar a referência</p>
        {errorMessage && <p className="text-xs text-red-300 mt-1">{errorMessage}</p>}
      </div>
    );
  }

  const currentIdx = STEP_ORDER.indexOf(status);
  const progress = STAGE_PROGRESS[status] ?? 0;
  const isRunning = status !== "done";

  return (
    <div className="flex flex-col gap-4">
      <div>
        <div className="flex items-center justify-between mb-1.5">
          <span className="text-xs font-medium text-gray-400">
            {STEPS.find((s) => s.key === status)?.label ?? "Na fila"}
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
                <div className={`w-8 h-0.5 mb-4 ${currentIdx > stepIdx ? "bg-emerald-700" : "bg-gray-800"}`} />
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}
