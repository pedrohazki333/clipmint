"use client";

import Link from "next/link";
import type { Reference } from "@/lib/types";

const STATUS_LABEL: Record<string, string> = {
  queued: "Na fila",
  downloading_source: "Baixando",
  extracting: "Preparando",
  transcribing: "Transcrevendo",
  aligning: "Localizando",
  watching: "Assistindo",
  analyzing: "Analisando",
  done: "Pronto",
  error: "Erro",
};

export default function ReferenceCard({ reference }: { reference: Reference }) {
  const r = reference;
  const isError = r.status === "error";
  const isDone = r.status === "done";

  return (
    <Link
      href={`/references/${r.id}`}
      className="block rounded-md bg-raised border border-line hover:border-line-strong p-4 transition-colors"
    >
      <div className="flex items-center justify-between gap-4">
        <div className="min-w-0">
          <p className="text-body font-medium text-ink truncate">
            {r.source_title || r.source_url || "Clipe sem título"}
          </p>
          <p className="text-label text-ink-dim truncate mt-0.5">
            {[r.source_channel, r.kind === "standalone" ? "só o clipe" : "com o original"]
              .filter(Boolean)
              .join(" · ")}
          </p>
        </div>
        <div className="flex items-center gap-2 flex-shrink-0">
          {r.published && (
            <span className="rounded-full bg-mint-soft border border-mint/30 px-2.5 py-0.5 text-label text-mint">
              aprendido
            </span>
          )}
          <span
            className={`rounded-full px-2.5 py-0.5 text-label border ${
              isError
                ? "bg-danger-soft border-danger/40 text-danger"
                : isDone
                ? "bg-inset border-line text-ink"
                : "bg-inset border-line text-ink-dim animate-pulse"
            }`}
          >
            {STATUS_LABEL[r.status] ?? r.status}
          </span>
        </div>
      </div>
    </Link>
  );
}
