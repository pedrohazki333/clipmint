"use client";

import Link from "next/link";
import { useEffect, useRef, useState } from "react";
import { Film, MoreHorizontal } from "lucide-react";

import { deleteJob, getApiErrorMessage } from "@/lib/api";
import type { Job } from "@/lib/types";

/**
 * Uma linha de projeto: miniatura, título e o que se sabe dele.
 *
 * "Projeto" é um job — o vídeo de origem e os clipes que saíram dele. A linha
 * mostra só o que a listagem traz de verdade: título, canal, estado e quando foi
 * criado. A contagem de clipes não vem na listagem, e por isso não aparece aqui.
 */

const ESTADOS: Record<string, { rotulo: string; classe: string }> = {
  queued: { rotulo: "Na fila", classe: "bg-inset text-ink-dim" },
  downloading: { rotulo: "Baixando", classe: "bg-running-soft text-running" },
  transcribing: { rotulo: "Transcrevendo", classe: "bg-running-soft text-running" },
  analyzing: { rotulo: "Analisando", classe: "bg-running-soft text-running" },
  clipping: { rotulo: "Gerando clipes", classe: "bg-running-soft text-running" },
  done: { rotulo: "Pronto", classe: "bg-mint-soft text-mint-ink" },
  error: { rotulo: "Erro", classe: "bg-danger-soft text-danger" },
};

const EM_ANDAMENTO = new Set(["queued", "downloading", "transcribing", "analyzing", "clipping"]);

export function estaEmAndamento(job: Job): boolean {
  return EM_ANDAMENTO.has(job.status);
}

const relativo = new Intl.RelativeTimeFormat("pt-BR", { numeric: "auto" });

/** "há 2 horas", "ontem", "há 3 dias" — e a data, passado um mês. */
export function quando(iso: string): string {
  const data = new Date(iso);
  const seg = (data.getTime() - Date.now()) / 1000;
  const abs = Math.abs(seg);
  if (abs < 60) return "agora";
  if (abs < 3600) return relativo.format(Math.round(seg / 60), "minute");
  if (abs < 86400) return relativo.format(Math.round(seg / 3600), "hour");
  if (abs < 86400 * 30) return relativo.format(Math.round(seg / 86400), "day");
  return data.toLocaleDateString("pt-BR", { day: "2-digit", month: "short", year: "numeric" });
}

export function duracao(segundos: number | null): string | null {
  if (!segundos) return null;
  const s = Math.round(segundos);
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  const r = s % 60;
  return h > 0
    ? `${h}:${String(m).padStart(2, "0")}:${String(r).padStart(2, "0")}`
    : `${m}:${String(r).padStart(2, "0")}`;
}

export function EstadoProjeto({ status }: { status: string }) {
  const e = ESTADOS[status] ?? { rotulo: status, classe: "bg-inset text-ink-dim" };
  return (
    <span className={`inline-flex items-center gap-1.5 rounded-sm px-2 py-0.5 text-label font-semibold ${e.classe}`}>
      {EM_ANDAMENTO.has(status) && (
        <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-current" aria-hidden />
      )}
      {e.rotulo}
    </span>
  );
}

export default function ProjectRow({
  job,
  onDeleted,
  compact = false,
}: {
  job: Job;
  onDeleted?: () => void;
  /** Versão do painel lateral: sem canal e sem o erro por extenso. */
  compact?: boolean;
}) {
  const [menu, setMenu] = useState(false);
  const [confirmando, setConfirmando] = useState(false);
  const [excluindo, setExcluindo] = useState(false);
  const [erro, setErro] = useState("");
  const menuRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!menu) return;
    function fora(e: MouseEvent) {
      if (!menuRef.current?.contains(e.target as Node)) {
        setMenu(false);
        setConfirmando(false);
      }
    }
    function esc(e: KeyboardEvent) {
      if (e.key === "Escape") {
        setMenu(false);
        setConfirmando(false);
      }
    }
    document.addEventListener("mousedown", fora);
    document.addEventListener("keydown", esc);
    return () => {
      document.removeEventListener("mousedown", fora);
      document.removeEventListener("keydown", esc);
    };
  }, [menu]);

  async function excluir() {
    if (!confirmando) {
      setConfirmando(true);
      return;
    }
    setExcluindo(true);
    try {
      await deleteJob(job.id);
      setMenu(false);
      onDeleted?.();
    } catch (err) {
      setErro(getApiErrorMessage(err, "Não foi possível excluir este projeto."));
      setExcluindo(false);
      setConfirmando(false);
    }
  }

  const titulo = job.video_title ?? job.youtube_url;
  const dur = duracao(job.duration_seconds);

  return (
    <li className="group relative">
      <div
        className={`flex items-center gap-4 rounded-md border border-line bg-raised transition-colors duration-150 hover:border-line-strong ${
          compact ? "p-2.5" : "p-3"
        }`}
      >
        <Link href={`/jobs/${job.id}`} className="flex min-w-0 flex-1 items-center gap-4">
          <span
            className={`relative flex flex-shrink-0 items-center justify-center overflow-hidden rounded-sm bg-inset ${
              compact ? "h-14 w-24" : "h-16 w-28"
            }`}
          >
            {job.thumbnail_url ? (
              // eslint-disable-next-line @next/next/no-img-element
              <img src={job.thumbnail_url} alt="" className="h-full w-full object-cover" />
            ) : (
              <Film className="h-5 w-5 text-ink-muted" aria-hidden />
            )}
            {dur && (
              <span className="tabular absolute bottom-1 right-1 rounded-[3px] bg-ink/85 px-1 text-[0.6875rem] text-white">
                {dur}
              </span>
            )}
          </span>
          <span className="min-w-0 flex-1">
            <span className="block truncate font-display text-[0.9375rem] font-bold text-ink">
              {titulo}
            </span>
            <span className="mt-1.5 flex flex-wrap items-center gap-x-2.5 gap-y-1 text-label text-ink-muted">
              <EstadoProjeto status={job.status} />
              {!compact && job.channel_name && <span className="truncate">{job.channel_name}</span>}
              <span>{quando(job.created_at)}</span>
            </span>
          </span>
        </Link>

        <div ref={menuRef} className="relative flex-shrink-0">
          <button
            type="button"
            onClick={() => {
              setMenu((v) => !v);
              setConfirmando(false);
            }}
            aria-haspopup="menu"
            aria-expanded={menu}
            className="flex h-9 w-9 items-center justify-center rounded-md text-ink-dim transition-colors hover:bg-inset hover:text-ink"
          >
            <MoreHorizontal className="h-5 w-5" aria-hidden />
            <span className="sr-only">Ações de {titulo}</span>
          </button>
          {menu && (
            <div
              role="menu"
              className="absolute right-0 top-10 z-20 w-44 overflow-hidden rounded-md border border-line bg-raised py-1 shadow-[0_8px_24px_-12px_rgb(36_36_36/0.35)]"
            >
              <Link
                role="menuitem"
                href={`/jobs/${job.id}`}
                className="block px-3.5 py-2 text-body text-ink hover:bg-inset"
              >
                Abrir projeto
              </Link>
              <button
                role="menuitem"
                type="button"
                onClick={excluir}
                disabled={excluindo}
                className="block w-full px-3.5 py-2 text-left text-body text-danger hover:bg-danger-soft disabled:opacity-50"
              >
                {excluindo ? "Excluindo..." : confirmando ? "Confirmar exclusão" : "Excluir"}
              </button>
            </div>
          )}
        </div>
      </div>
      {!compact && job.status === "error" && job.error_message && (
        <p className="mt-1.5 truncate px-1 text-label text-danger">{job.error_message}</p>
      )}
      {erro && <p className="mt-1.5 px-1 text-label text-danger">{erro}</p>}
    </li>
  );
}
