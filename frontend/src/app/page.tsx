"use client";

import { useState, useEffect, useCallback } from "react";
import Link from "next/link";
import type { Job, Reference, SourceType, VideoEnhanceJob } from "@/lib/types";
import { listJobs, listReferences, listVideoEnhance } from "@/lib/api";
import ReferenceForm from "@/components/ReferenceForm";
import ReferenceCard from "@/components/ReferenceCard";
import LearnedPatterns from "@/components/LearnedPatterns";

const ACTIVE_POLLING_INTERVAL = 5000; // ms — só roda enquanto houver job em andamento
// "error" é o terminal dos jobs de clipe; "failed", o dos tratamentos de vídeo.
const TERMINAL_STATUSES = new Set(["done", "error", "failed"]);

const NICHES: {
  source: SourceType;
  href: string;
  title: string;
  blurb: string;
  accent: string;
}[] = [
  {
    source: "podcast",
    href: "/podcast",
    title: "Podcast",
    blurb: "Gancho verbal, arco de resolução, frase-momento",
    accent: "hover:border-emerald-500",
  },
  {
    source: "gameplay",
    href: "/gameplay",
    title: "Gameplay",
    blurb: "Pico visual, reviravolta, legibilidade sem som",
    accent: "hover:border-sky-500",
  },
  {
    source: "siege",
    href: "/siege",
    title: "Siege X",
    blurb: "Sequência de abates, clutch, reflexo e treta na call",
    accent: "hover:border-orange-500",
  },
];

export default function Home() {
  const [jobs, setJobs] = useState<Job[]>([]);
  const [references, setReferences] = useState<Reference[]>([]);
  const [enhanceJobs, setEnhanceJobs] = useState<VideoEnhanceJob[]>([]);

  const fetchJobs = useCallback(async () => {
    try {
      setJobs(await listJobs());
    } catch {
      // silencioso — o hub é só um resumo; o erro real aparece na página da conta
    }
  }, []);

  const fetchReferences = useCallback(async () => {
    try {
      setReferences(await listReferences());
    } catch {
      // silencioso — a lista de referências é secundária
    }
  }, []);

  const fetchEnhanceJobs = useCallback(async () => {
    try {
      setEnhanceJobs(await listVideoEnhance());
    } catch {
      // silencioso — o card mostra só a contagem; o erro real aparece na página
    }
  }, []);

  useEffect(() => {
    fetchJobs();
    fetchReferences();
    fetchEnhanceJobs();
  }, [fetchJobs, fetchReferences, fetchEnhanceJobs]);

  const hasActiveWork =
    jobs.some((j) => !TERMINAL_STATUSES.has(j.status)) ||
    references.some((r) => !TERMINAL_STATUSES.has(r.status)) ||
    enhanceJobs.some((v) => !TERMINAL_STATUSES.has(v.status));
  useEffect(() => {
    if (!hasActiveWork) return;
    const interval = setInterval(() => {
      fetchJobs();
      fetchReferences();
      fetchEnhanceJobs();
    }, ACTIVE_POLLING_INTERVAL);
    return () => clearInterval(interval);
  }, [hasActiveWork, fetchJobs, fetchReferences, fetchEnhanceJobs]);

  function summary(source: SourceType) {
    const mine = jobs.filter((j) => j.source_type === source);
    return {
      total: mine.length,
      running: mine.filter((j) => !TERMINAL_STATUSES.has(j.status)).length,
    };
  }

  return (
    <div className="flex flex-col gap-8">
      <div>
        <h1 className="text-xl font-bold text-gray-100 mb-1">Suas contas</h1>
        <p className="text-sm text-gray-500">
          Cada conta tem os próprios presets de marca e a própria fila de postagem.
        </p>
      </div>

      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
        {NICHES.map((niche) => {
          const { total, running } = summary(niche.source);
          return (
            <Link
              key={niche.source}
              href={niche.href}
              className={`rounded-2xl bg-gray-900 border border-gray-800 p-6 transition-colors ${niche.accent}`}
            >
              <h2 className="text-lg font-semibold text-gray-100">{niche.title}</h2>
              <p className="mt-1 text-sm text-gray-500">{niche.blurb}</p>
              <div className="mt-4 flex items-center gap-3 text-sm">
                <span className="text-gray-300">
                  {total} {total === 1 ? "vídeo" : "vídeos"}
                </span>
                {running > 0 && (
                  <span className="rounded-full bg-amber-500/10 border border-amber-500/30 px-2 py-0.5 text-xs text-amber-400">
                    {running} processando
                  </span>
                )}
              </div>
            </Link>
          );
        })}

        {/* Melhorar vídeo não é uma conta: não tem source_type nem fila de
            postagem, então a contagem vem da própria API, não de `summary`. */}
        <Link
          href="/melhorar-video"
          className="rounded-2xl bg-gray-900 border border-gray-800 p-6 transition-colors hover:border-fuchsia-500"
        >
          <h2 className="text-lg font-semibold text-gray-100">Melhorar vídeo</h2>
          <p className="mt-1 text-sm text-gray-500">
            Vídeo do Gemini sai em 1080p com bitrate limpo
          </p>
          <div className="mt-4 flex items-center gap-3 text-sm">
            <span className="text-gray-300">
              {enhanceJobs.length} {enhanceJobs.length === 1 ? "vídeo" : "vídeos"}
            </span>
            {enhanceJobs.some((v) => !TERMINAL_STATUSES.has(v.status)) && (
              <span className="rounded-full bg-amber-500/10 border border-amber-500/30 px-2 py-0.5 text-xs text-amber-400">
                {enhanceJobs.filter((v) => !TERMINAL_STATUSES.has(v.status)).length} processando
              </span>
            )}
          </div>
        </Link>
      </div>

      {/* Aprender com clipe viral de outro criador — vale para as três contas */}
      <ReferenceForm />

      {references.length > 0 && (
        <div>
          <h2 className="text-lg font-semibold text-gray-300 mb-4">Referências</h2>
          <div className="flex flex-col gap-3">
            {references.map((r) => (
              <ReferenceCard key={r.id} reference={r} />
            ))}
          </div>
        </div>
      )}

      <LearnedPatterns />
    </div>
  );
}
