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

interface Props {
  status: JobStatus;
  errorMessage?: string | null;
}

export default function JobStatus({ status, errorMessage }: Props) {
  if (status === "error") {
    return (
      <div className="rounded-lg bg-red-900/30 border border-red-800 p-4">
        <p className="text-sm font-semibold text-red-400">Pipeline falhou</p>
        {errorMessage && <p className="text-xs text-red-300 mt-1">{errorMessage}</p>}
      </div>
    );
  }

  const currentIdx = STEP_ORDER.indexOf(status);

  return (
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
  );
}
