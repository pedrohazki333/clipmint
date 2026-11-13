"use client";

import { useEffect, useRef, useState } from "react";
import { Check, X } from "lucide-react";

import type { JobStatus, StageMark, StageProgress } from "@/lib/types";

/**
 * O andamento do job, etapa por etapa, cada uma com a sua barra.
 *
 * Uma versão antiga mostrava uma barra única com porcentagem fixa por etapa —
 * 12% durante todo o download — pulsando parada por vinte minutos. Ela estimava
 * algo que ninguém sabia, e a estimativa era sempre a mesma para um vídeo de
 * três minutos e para uma live de seis horas.
 *
 * Agora a largura vem do servidor (`progress`). No download ela é a fração de
 * bytes, e na geração de clipes, a de clipes prontos. Na transcrição e na
 * análise, que não têm contador, é o tempo que a etapa levou nos jobs
 * anteriores, proporcional à duração do vídeo — e a barra desacelera se a etapa
 * passar disso, sem nunca encher sozinha: quem enche é a etapa acabar.
 *
 * O tempo das etapas concluídas fica à vista: uma etapa travada se denuncia.
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
  clipsReady?: number;
  clipsTotal?: number;
  stageLog?: StageMark[] | null;
  progress?: StageProgress | null;
}

/**
 * O trecho sem contador: anda reto até ~90% no tempo esperado e, se passar
 * dele, desacelera em direção ao fim sem chegar lá.
 */
function curva(x: number): number {
  if (x <= 1) return 0.9 * Math.max(0, x);
  return 0.9 + 0.09 * (1 - Math.exp(-(x - 1) * 1.5));
}

type Amostra = { p: StageProgress; em: number };

/**
 * A fração a desenhar agora, entre uma resposta do servidor e a próxima.
 *
 * As respostas chegam a cada 2 s; desenhar só nelas faria a barra andar aos
 * saltos. Entre elas: no trecho estimado, o relógio continua a curva; no
 * medido, a barra segue na velocidade das duas últimas medidas, sem passar do
 * que a próxima medida deve trazer.
 */
function useFracaoAoVivo(status: JobStatus, progress: StageProgress | null | undefined): number | null {
  const [amostras, setAmostras] = useState<{ atual: Amostra | null; anterior: Amostra | null }>({
    atual: null,
    anterior: null,
  });
  const maior = useRef<{ status: JobStatus; valor: number }>({ status, valor: 0 });
  const [agora, setAgora] = useState(0);

  useEffect(() => {
    if (!progress) return;
    const em = performance.now();
    setAmostras((s) => ({ atual: { p: progress, em }, anterior: s.atual }));
    setAgora(em);
  }, [progress]);

  const rodando = !!progress;
  useEffect(() => {
    if (!rodando) return;
    const t = setInterval(() => setAgora(performance.now()), 200);
    return () => clearInterval(t);
  }, [rodando]);

  if (maior.current.status !== status) maior.current = { status, valor: 0 };
  const a = amostras.atual;
  if (!progress || !a) return null;

  const dt = Math.max(0, (agora - a.em) / 1000);
  let valor: number;
  if (a.p.expected_seconds && a.p.span > 0) {
    valor = a.p.base + a.p.span * curva((a.p.elapsed_seconds + dt) / a.p.expected_seconds);
  } else {
    const b = amostras.anterior;
    const intervalo = b ? (a.em - b.em) / 1000 : 0;
    const passo = b && intervalo > 0 && a.p.base > b.p.base ? a.p.base - b.p.base : 0;
    valor = intervalo > 0 ? a.p.base + passo * Math.min(1, dt / intervalo) : a.p.base;
  }
  // Nunca recua na mesma etapa: uma medida nova menor que a extrapolação
  // espera a barra em vez de puxá-la de volta.
  valor = Math.max(maior.current.valor, Math.min(0.995, valor));
  maior.current.valor = valor;
  return valor;
}

/** Segundos → "4:12" ou "1:02:30". */
export function formatDuration(seconds: number): string {
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
export function stageDurations(
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

/** Em que etapa o job estava quando parou: a última marca que não é terminal. */
function etapaQueFalhou(marks: StageMark[] | null | undefined): JobStatus | null {
  if (!marks) return null;
  for (let i = marks.length - 1; i >= 0; i--) {
    if (marks[i].s !== "error" && marks[i].s !== "done") return marks[i].s;
  }
  return null;
}

type Estado = "feita" | "ativa" | "falhou" | "pendente";

export default function JobStatus({ status, clipsReady = 0, clipsTotal = 0, stageLog, progress }: Props) {
  const aoVivo = useFracaoAoVivo(status, progress);
  const duracoes = stageDurations(stageLog, Date.now());

  // No erro, o lugar na sequência é o da etapa que estava rodando.
  const falhou = status === "error" ? etapaQueFalhou(stageLog) : null;
  const posicao = ORDER.indexOf(falhou ?? status);

  function estadoDe(key: JobStatus): Estado {
    const i = ORDER.indexOf(key);
    if (status === "error") {
      if (key === falhou) return "falhou";
      return falhou && i < posicao ? "feita" : "pendente";
    }
    if (i < posicao) return "feita";
    if (i === posicao) return "ativa";
    return "pendente";
  }

  return (
    <ol className="grid grid-cols-2 gap-x-4 gap-y-5 sm:grid-cols-4" aria-label="Etapas do processamento">
      {STAGES.map((etapa, n) => {
        const estado = estadoDe(etapa.key);
        const segundos = duracoes.get(etapa.key);
        const emClipes = etapa.key === "clipping" && estado === "ativa" && clipsTotal > 0;
        // Sem resposta de progresso (o servidor reiniciou, ou é outro processo),
        // a geração ainda tem a contagem de clipes; as demais, só o pulso.
        const fracao =
          estado !== "ativa" ? null : (aoVivo ?? (emClipes ? clipsReady / clipsTotal : null));
        const largura = estado === "pendente" ? 0 : estado === "ativa" ? (fracao ?? 0) * 100 : 100;

        return (
          <li key={etapa.key} aria-current={estado === "ativa" ? "step" : undefined} className="min-w-0">
            {/* A régua de cima. Um elemento só do começo ao fim da etapa, para
                que ao terminar ela corra até o fim em vez de trocar de repente. */}
            <div
              className="relative h-1.5 overflow-hidden rounded-full bg-line"
              {...(estado === "ativa" && {
                role: "progressbar",
                "aria-label": `Andamento: ${etapa.label}`,
                ...(fracao !== null && {
                  "aria-valuemin": 0,
                  "aria-valuemax": 100,
                  "aria-valuenow": Math.round(fracao * 100),
                }),
              })}
            >
              {estado === "ativa" && fracao === null ? (
                <div className="absolute inset-0 animate-pulse bg-coral/50" />
              ) : (
                <div
                  className={`absolute inset-y-0 left-0 rounded-full transition-[width,background-color] ease-linear ${
                    estado === "feita"
                      ? "bg-ink duration-500"
                      : estado === "falhou"
                        ? "bg-danger duration-500"
                        : "cm-progress-fill duration-200"
                  }`}
                  style={{ width: `${largura}%` }}
                />
              )}
            </div>

            <div className="mt-3 flex items-center gap-2">
              <span className="tabular text-label text-ink-muted">{String(n + 1).padStart(2, "0")}</span>
              {estado === "feita" && <Check className="h-3.5 w-3.5 text-mint-ink" aria-label="concluída" />}
              {estado === "falhou" && <X className="h-3.5 w-3.5 text-danger" aria-label="parou aqui" />}
              {estado === "ativa" && (
                <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-coral" aria-label="em andamento" />
              )}
            </div>
            <p
              className={`mt-1 font-display text-[0.9375rem] font-bold ${
                estado === "pendente" ? "text-ink-muted" : estado === "falhou" ? "text-danger" : "text-ink"
              }`}
            >
              {etapa.label}
            </p>
            <p className="tabular mt-0.5 text-label text-ink-muted">
              {emClipes && `${clipsReady} de ${clipsTotal} · `}
              {estado === "pendente"
                ? "—"
                : segundos !== undefined
                  ? formatDuration(segundos)
                  : estado === "ativa"
                    ? "0:00"
                    : "—"}
            </p>
          </li>
        );
      })}
    </ol>
  );
}
