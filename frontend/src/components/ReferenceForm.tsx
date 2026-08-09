"use client";

import { useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { createReference, getApiErrorMessage } from "@/lib/api";

const ACCEPT = ".mp4,.mov,.mkv,.webm,.avi,.m4v";

export default function ReferenceForm() {
  const router = useRouter();
  const [url, setUrl] = useState("");
  const [clip, setClip] = useState<File | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const fileInputRef = useRef<HTMLInputElement>(null);

  function isValidYouTubeUrl(u: string): boolean {
    return /(?:youtube\.com\/(watch\?|shorts\/|live\/)|youtu\.be\/)/.test(u);
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError("");

    if (!isValidYouTubeUrl(url.trim())) {
      setError("URL inválida do vídeo original. Use um link do YouTube.");
      return;
    }
    if (!clip) {
      setError("Envie o arquivo do clipe viral.");
      return;
    }

    setBusy(true);
    try {
      const ref = await createReference(url.trim(), clip);
      router.push(`/references/${ref.id}`);
    } catch (err) {
      setError(getApiErrorMessage(err, "Erro ao criar a referência. Tente novamente."));
      setBusy(false);
    }
  }

  return (
    <div className="rounded-2xl bg-gray-900 border border-gray-800 p-6">
      <h2 className="text-base font-semibold text-gray-100">Aprender com clipe viral</h2>
      <p className="text-sm text-gray-500 mt-1 mb-5">
        Envie um clipe que já viralizou (de outro criador) e o vídeo original de onde ele saiu. O
        ClipMint localiza o corte, entende por que funcionou e passa a usar isso como referência.
      </p>

      <form onSubmit={handleSubmit} className="flex flex-col gap-4">
        <div className="flex flex-col gap-2">
          <label htmlFor="ref-url" className="text-sm font-medium text-gray-400">
            URL do vídeo original (YouTube)
          </label>
          <input
            id="ref-url"
            type="text"
            value={url}
            onChange={(e) => setUrl(e.target.value)}
            placeholder="https://www.youtube.com/watch?v=..."
            disabled={busy}
            className="w-full rounded-lg bg-gray-800 border border-gray-700 px-4 py-3 text-gray-100 placeholder-gray-500 focus:outline-none focus:border-emerald-500 disabled:opacity-50"
          />
        </div>

        <div className="flex flex-col gap-2">
          <label className="text-sm font-medium text-gray-400">Arquivo do clipe viral</label>
          <label
            className={`flex items-center justify-between gap-3 rounded-lg border border-dashed px-4 py-3 cursor-pointer transition-colors ${
              busy
                ? "border-gray-800 cursor-wait"
                : "border-gray-700 hover:border-emerald-500/60 bg-gray-800/40"
            }`}
          >
            <span className={`text-sm truncate ${clip ? "text-gray-200" : "text-gray-500"}`}>
              {clip ? clip.name : "Escolher arquivo de vídeo (mp4, mov, webm...)"}
            </span>
            <span className="text-xs text-gray-400 flex-shrink-0 rounded-md bg-gray-800 border border-gray-700 px-3 py-1.5">
              {clip ? "Trocar" : "Selecionar"}
            </span>
            <input
              ref={fileInputRef}
              type="file"
              accept={ACCEPT}
              className="hidden"
              disabled={busy}
              onChange={(e) => setClip(e.target.files?.[0] ?? null)}
            />
          </label>
        </div>

        {error && (
          <p className="text-sm text-red-400 bg-red-900/20 rounded px-3 py-2">{error}</p>
        )}

        <button
          type="submit"
          disabled={busy}
          className="w-full rounded-lg bg-emerald-500 hover:bg-emerald-400 disabled:bg-gray-700 disabled:cursor-not-allowed px-6 py-3 font-semibold text-white transition-colors"
        >
          {busy ? "Enviando..." : "Analisar e aprender"}
        </button>
      </form>
    </div>
  );
}
