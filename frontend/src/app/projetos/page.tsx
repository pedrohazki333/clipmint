"use client";

import Link from "next/link";
import { useCallback, useEffect, useMemo, useState } from "react";
import { FolderOpen } from "lucide-react";

import ProjectRow, { estaEmAndamento } from "@/components/ProjectRow";
import { buttonClass, PageHeader } from "@/components/ui/editorial";
import { getApiErrorMessage, listJobs } from "@/lib/api";
import type { Job } from "@/lib/types";

type Filtro = "todos" | "andamento" | "prontos" | "erro";

const FILTROS: { valor: Filtro; rotulo: string; aceita: (j: Job) => boolean }[] = [
  { valor: "todos", rotulo: "Todos", aceita: () => true },
  { valor: "andamento", rotulo: "Em andamento", aceita: estaEmAndamento },
  { valor: "prontos", rotulo: "Prontos", aceita: (j) => j.status === "done" },
  { valor: "erro", rotulo: "Com erro", aceita: (j) => j.status === "error" },
];

/**
 * Projetos: todos os vídeos que viraram (ou estão virando) clipes.
 *
 * Mesma listagem de jobs que a API sempre teve (`GET /api/jobs`). Enquanto houver
 * algum em andamento, a lista se atualiza sozinha — é o que a pessoa vem conferir.
 */
export default function ProjetosPage() {
  const [jobs, setJobs] = useState<Job[] | null>(null);
  const [erro, setErro] = useState("");
  const [filtro, setFiltro] = useState<Filtro>("todos");

  const carregar = useCallback(async () => {
    try {
      setJobs(await listJobs());
      setErro("");
    } catch (err) {
      setErro(getApiErrorMessage(err, "Não foi possível carregar os projetos."));
    }
  }, []);

  useEffect(() => {
    carregar();
  }, [carregar]);

  const algumRodando = useMemo(() => (jobs ?? []).some(estaEmAndamento), [jobs]);
  useEffect(() => {
    if (!algumRodando) return;
    const t = setInterval(carregar, 5000);
    return () => clearInterval(t);
  }, [algumRodando, carregar]);

  const visiveis = useMemo(() => {
    const regra = FILTROS.find((f) => f.valor === filtro)!;
    return (jobs ?? []).filter(regra.aceita);
  }, [jobs, filtro]);

  return (
    <div className="flex flex-col gap-8">
      <PageHeader
        eyebrow="Seus vídeos"
        title="Projetos"
        description="Cada vídeo que você mandou, com o estado dos clipes dele."
        actions={
          <Link href="/gerar" className={buttonClass("primary")}>
            Novo projeto
          </Link>
        }
      />

      {jobs && jobs.length > 0 && (
        <div role="group" aria-label="Filtrar projetos" className="flex flex-wrap gap-2 border-b border-line pb-5">
          {FILTROS.map((f) => {
            const n = jobs.filter(f.aceita).length;
            const ativo = filtro === f.valor;
            return (
              <button
                key={f.valor}
                type="button"
                onClick={() => setFiltro(f.valor)}
                aria-pressed={ativo}
                className={`inline-flex items-center gap-2 rounded-md border px-3.5 py-2 text-body font-medium transition-colors duration-150 ${
                  ativo
                    ? "border-ink bg-ink text-base"
                    : "border-line bg-raised text-ink-dim hover:border-line-strong hover:text-ink"
                }`}
              >
                {f.rotulo}
                <span className={`tabular text-label ${ativo ? "text-base/70" : "text-ink-muted"}`}>{n}</span>
              </button>
            );
          })}
        </div>
      )}

      {erro && (
        <p className="rounded-md border border-danger/30 bg-danger-soft px-4 py-3 text-body text-danger">{erro}</p>
      )}

      {!jobs && !erro && <p className="py-16 text-center text-ink-dim">Carregando...</p>}

      {jobs && jobs.length === 0 && (
        <div className="flex flex-col items-start gap-4 rounded-lg border border-dashed border-line-strong px-6 py-12 sm:px-10">
          <FolderOpen className="h-7 w-7 text-ink-muted" aria-hidden />
          <div>
            <p className="font-display text-title font-bold text-ink">Nenhum projeto ainda</p>
            <p className="mt-1 text-body text-ink-dim">
              Cole o link de um vídeo do YouTube e os clipes aparecem aqui.
            </p>
          </div>
          <Link href="/gerar" className={buttonClass("primary")}>
            Gerar os primeiros clipes
          </Link>
        </div>
      )}

      {jobs && jobs.length > 0 && visiveis.length === 0 && (
        <p className="py-10 text-center text-body text-ink-dim">Nenhum projeto neste filtro.</p>
      )}

      {visiveis.length > 0 && (
        <ul className="flex flex-col gap-2.5">
          {visiveis.map((job) => (
            <ProjectRow key={job.id} job={job} onDeleted={carregar} />
          ))}
        </ul>
      )}
    </div>
  );
}
