"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";

import { AvatarIcon } from "@/lib/avatars";
import { PUBLIC_NICHES } from "@/lib/features";
import { LearningSection, PERSONAL_NICHES, PERSONAL_TOOLS } from "@/personal";
import { getApiErrorMessage, listProfiles } from "@/lib/api";
import type { Profile } from "@/lib/types";
import type { ToolCount } from "@/lib/features";

/**
 * Meus perfis — a entrada do sistema.
 *
 * Antes esta tela listava "contas", que eram um enum fixo no código: dava para
 * entrar nelas, mas não para criar, renomear ou ter duas do mesmo tipo. O perfil
 * é a mesma ideia com lugar para morar.
 */

const ACTIVE_POLLING_INTERVAL = 5000; // ms — só enquanto houver trabalho rodando
const NICHES = [...PUBLIC_NICHES, ...PERSONAL_NICHES];

function tempoRelativo(iso: string | null): string {
  if (!iso) return "Ainda não gerou nada";
  const dias = Math.floor((Date.now() - Date.parse(iso)) / 86_400_000);
  if (dias <= 0) return "Última geração hoje";
  if (dias === 1) return "Última geração ontem";
  if (dias < 30) return `Última geração há ${dias} dias`;
  return "Última geração há mais de um mês";
}

export default function Home() {
  const [profiles, setProfiles] = useState<Profile[] | null>(null);
  const [toolCounts, setToolCounts] = useState<Record<string, ToolCount>>({});
  const [erro, setErro] = useState("");

  const carregarPerfis = useCallback(async () => {
    try {
      setProfiles(await listProfiles());
      setErro("");
    } catch (err) {
      setProfiles([]);
      setErro(getApiErrorMessage(err, "Não foi possível carregar seus perfis."));
    }
  }, []);

  const carregarFerramentas = useCallback(async () => {
    const entradas = await Promise.all(
      PERSONAL_TOOLS.map(async (tool) => {
        try {
          return [tool.key, await tool.loadCount()] as const;
        } catch {
          return null;
        }
      }),
    );
    const achadas = entradas.filter((e): e is readonly [string, ToolCount] => e !== null);
    if (achadas.length) {
      setToolCounts((prev) => ({ ...prev, ...Object.fromEntries(achadas) }));
    }
  }, []);

  useEffect(() => {
    carregarPerfis();
    carregarFerramentas();
  }, [carregarPerfis, carregarFerramentas]);

  const rodando = Object.values(toolCounts).some((c) => c.running > 0);
  useEffect(() => {
    if (!rodando) return;
    const t = setInterval(() => {
      carregarPerfis();
      carregarFerramentas();
    }, ACTIVE_POLLING_INTERVAL);
    return () => clearInterval(t);
  }, [rodando, carregarPerfis, carregarFerramentas]);

  return (
    <div className="flex flex-col gap-8">
      <div>
        <h1 className="text-display font-semibold text-ink">Meus perfis</h1>
        <p className="mt-1 text-body text-ink-dim">
          Cada perfil guarda a rubrica, a marca e o padrão de geração dos seus
          clipes.
        </p>
      </div>

      {erro && (
        <p className="rounded-sm border border-danger/40 bg-danger-soft px-3 py-2 text-body text-danger">
          {erro}
        </p>
      )}

      {profiles === null ? (
        <p className="py-12 text-center text-ink-dim">Carregando...</p>
      ) : profiles.length === 0 && !erro ? (
        <div className="rounded-md border border-dashed border-line bg-raised px-6 py-16 text-center">
          <p className="text-title font-medium text-ink">Ainda não há perfis</p>
          <p className="mt-1 text-body text-ink-dim">
            Crie o primeiro perfil para começar a gerar clipes.
          </p>
          <Link
            href="/perfis/novo"
            className="mt-5 inline-block rounded-sm bg-mint-strong px-5 py-2.5 text-body font-medium text-base transition-colors hover:bg-mint"
          >
            Criar primeiro perfil
          </Link>
        </div>
      ) : (
        <div className="grid gap-3 sm:grid-cols-2 sm:gap-4 lg:grid-cols-3">
          {profiles.map((p) => {
            const nicho = NICHES.find((n) => n.source === p.source_type);
            return (
              <Link
                key={p.id}
                href={`/perfis/${p.id}`}
                className={`flex flex-col rounded-md border border-line bg-raised p-5 transition-colors ${
                  nicho?.accent ?? "hover:border-line-strong"
                }`}
              >
                <div className="mb-3 flex h-11 w-11 items-center justify-center rounded-sm border border-line bg-inset text-mint">
                  <AvatarIcon name={p.avatar} className="h-5 w-5" />
                </div>
                <h2 className="truncate text-title font-semibold text-ink">
                  {p.name}
                </h2>
                <p className="text-body text-ink-dim">
                  {nicho?.title ?? p.source_type}
                </p>
                <dl className="mt-4 flex flex-col gap-1 text-label text-ink-muted">
                  <div className="flex items-center gap-1.5">
                    <span className="tabular text-ink-dim">{p.job_count}</span>
                    <span>{p.job_count === 1 ? "vídeo gerado" : "vídeos gerados"}</span>
                  </div>
                  <div>{tempoRelativo(p.last_generated_at)}</div>
                </dl>
              </Link>
            );
          })}

          <Link
            href="/perfis/novo"
            className="flex flex-col items-center justify-center gap-2 rounded-md border border-dashed border-line bg-raised p-5 text-center transition-colors hover:border-mint"
          >
            <span className="flex h-11 w-11 items-center justify-center rounded-sm border border-line bg-inset text-mint">
              <svg viewBox="0 0 24 24" className="h-5 w-5" fill="none" stroke="currentColor" strokeWidth="1.75" strokeLinecap="round" aria-hidden="true">
                <path d="M12 5v14M5 12h14" />
              </svg>
            </span>
            <span className="text-body font-medium text-ink">Criar novo perfil</span>
            <span className="text-label text-ink-muted">
              Configure um novo padrão de geração.
            </span>
          </Link>

          {/* Ferramentas que não são perfis: sem rubrica, sem fila de postagem. */}
          {PERSONAL_TOOLS.map((tool) => {
            const c = toolCounts[tool.key] ?? { total: 0, running: 0 };
            return (
              <Link
                key={tool.key}
                href={tool.href}
                className={`flex flex-col rounded-md border border-line bg-raised p-5 transition-colors ${tool.accent}`}
              >
                <h2 className="text-title font-semibold text-ink">{tool.title}</h2>
                <p className="mt-1 text-body text-ink-dim">{tool.blurb}</p>
                <div className="mt-4 flex items-center gap-3 text-label">
                  <span className="tabular text-ink-dim">
                    {c.total} {c.total === 1 ? "vídeo" : "vídeos"}
                  </span>
                  {c.running > 0 && (
                    <span className="rounded-full border border-running/30 bg-running-soft px-2 py-0.5 text-running">
                      {c.running} processando
                    </span>
                  )}
                </div>
              </Link>
            );
          })}
        </div>
      )}

      {/* Aprender com clipe viral e padrões — só na versão pessoal. */}
      {LearningSection && <LearningSection />}
    </div>
  );
}
