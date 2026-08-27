import type { ReferenceKind, ReferenceStatus } from "@/lib/types";

/**
 * As etapas de cada modo (ver ReferenceKind em lib/types.ts).
 *
 * São listas separadas porque os dois pipelines não passam pelos mesmos
 * lugares: o alinhado baixa o vídeo original e procura o corte dentro dele; o
 * standalone não tem original nenhum e, em vez disso, olha o clipe — quadro a
 * quadro, junto com a curva de som.
 */
const STEPS: Record<ReferenceKind, { key: ReferenceStatus; label: string }[]> = {
  aligned: [
    { key: "downloading_source", label: "Baixando" },
    { key: "transcribing", label: "Transcrição" },
    { key: "aligning", label: "Localizando" },
    { key: "analyzing", label: "Análise IA" },
    { key: "done", label: "Pronto" },
  ],
  standalone: [
    { key: "extracting", label: "Preparando" },
    { key: "transcribing", label: "Transcrição" },
    { key: "watching", label: "Assistindo" },
    { key: "analyzing", label: "Perícia" },
    { key: "done", label: "Pronto" },
  ],
};

const STEP_ORDER: Record<ReferenceKind, ReferenceStatus[]> = {
  aligned: ["queued", "downloading_source", "transcribing", "aligning", "analyzing", "done"],
  standalone: ["queued", "extracting", "transcribing", "watching", "analyzing", "done"],
};

interface Props {
  status: ReferenceStatus;
  kind?: ReferenceKind;
  errorMessage?: string | null;
}

/**
 * O andamento de uma referência.
 *
 * Sem porcentagem, pelo mesmo motivo do JobStatus: a que existia aqui era fixa
 * por etapa e valia igual para um clipe de 30s e para o download de um vídeo
 * original de duas horas. Aqui não há sequer registro de tempo por etapa (o
 * pipeline de referência não o guarda), então o honesto é mostrar só o que se
 * sabe: quais etapas passaram e qual está rodando.
 */
export default function ReferenceStatus({
  status,
  kind = "aligned",
  errorMessage,
}: Props) {
  if (status === "error") {
    return (
      <div
        role="alert"
        className="rounded-md border border-danger/40 bg-danger-soft p-3"
      >
        <p className="text-body font-medium text-danger">A leitura parou</p>
        {errorMessage && (
          <p className="mt-1 text-label text-ink-dim">{errorMessage}</p>
        )}
      </div>
    );
  }

  const etapas = STEPS[kind];
  const ordem = STEP_ORDER[kind];
  const atual = ordem.indexOf(status);

  return (
    <ol className="flex flex-wrap items-center gap-x-3 gap-y-1.5">
      {etapas.map((etapa) => {
        const idx = ordem.indexOf(etapa.key);
        const feita = atual > idx;
        const ativa = atual === idx;
        return (
          <li
            key={etapa.key}
            aria-current={ativa ? "step" : undefined}
            className={`flex items-center gap-1.5 text-label ${
              ativa ? "font-medium text-ink" : feita ? "text-mint" : "text-ink-muted"
            }`}
          >
            {feita ? (
              <svg viewBox="0 0 12 12" className="h-3 w-3 flex-shrink-0" aria-hidden="true">
                <path
                  d="M2.5 6.5l2.5 2.5 4.5-5"
                  fill="none"
                  stroke="currentColor"
                  strokeWidth="1.75"
                  strokeLinecap="round"
                  strokeLinejoin="round"
                />
              </svg>
            ) : (
              <span
                className={`h-1.5 w-1.5 flex-shrink-0 rounded-full ${
                  ativa ? "animate-pulse bg-running" : "bg-line-strong"
                }`}
                aria-hidden="true"
              />
            )}
            {etapa.label}
          </li>
        );
      })}
    </ol>
  );
}
