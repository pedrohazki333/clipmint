"use client";

import Link from "next/link";
import type { Reference } from "@/lib/types";

const STATUS_LABEL: Record<string, string> = {
  queued: "Na fila",
  downloading_source: "Baixando",
  transcribing: "Transcrevendo",
  aligning: "Localizando",
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
      className="block rounded-xl bg-gray-900 border border-gray-800 hover:border-gray-700 p-4 transition-colors"
    >
      <div className="flex items-center justify-between gap-4">
        <div className="min-w-0">
          <p className="text-sm font-medium text-gray-200 truncate">
            {r.source_title ?? r.source_url}
          </p>
          {r.source_channel && (
            <p className="text-xs text-gray-500 truncate mt-0.5">{r.source_channel}</p>
          )}
        </div>
        <div className="flex items-center gap-2 flex-shrink-0">
          {r.published && (
            <span className="rounded-full bg-emerald-900/40 border border-emerald-800 px-2.5 py-0.5 text-xs text-emerald-300">
              aprendido
            </span>
          )}
          <span
            className={`rounded-full px-2.5 py-0.5 text-xs border ${
              isError
                ? "bg-red-900/30 border-red-800 text-red-400"
                : isDone
                ? "bg-gray-800 border-gray-700 text-gray-300"
                : "bg-gray-800 border-gray-700 text-gray-400 animate-pulse"
            }`}
          >
            {STATUS_LABEL[r.status] ?? r.status}
          </span>
        </div>
      </div>
    </Link>
  );
}
