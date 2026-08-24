"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import type { SourceType } from "@/lib/types";
import {
  createReference,
  createStandaloneReference,
  getApiErrorMessage,
} from "@/lib/api";

const ACCEPT = ".mp4,.mov,.mkv,.webm,.avi,.m4v";

/**
 * Os dois jeitos de aprender com um clipe alheio.
 *
 * "standalone" é o padrão porque é o caso que realmente acontece: um clipe
 * salvo do TikTok não diz de onde saiu. "aligned" só vale a pena quando se tem
 * o original em mãos — aí a análise fica melhor, porque passa a saber o que o
 * outro criador deixou de fora.
 */
type Mode = "standalone" | "aligned";

const NICHES: { value: SourceType; label: string }[] = [
  { value: "podcast", label: "Podcast" },
  { value: "gameplay", label: "Gameplay" },
  { value: "siege", label: "Siege X" },
];

const FIELD =
  "w-full rounded-lg bg-gray-800 border border-gray-700 px-4 py-3 text-gray-100 placeholder-gray-500 focus:outline-none focus:border-emerald-500 disabled:opacity-50";

export default function ReferenceForm() {
  const router = useRouter();
  const [mode, setMode] = useState<Mode>("standalone");
  const [clip, setClip] = useState<File | null>(null);
  const [sourceType, setSourceType] = useState<SourceType>("podcast");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  // Só no modo alinhado
  const [url, setUrl] = useState("");

  // Só no modo standalone — todos opcionais
  const [title, setTitle] = useState("");
  const [channel, setChannel] = useState("");
  const [postUrl, setPostUrl] = useState("");
  const [notas, setNotas] = useState("");

  function isValidYouTubeUrl(u: string): boolean {
    return /(?:youtube\.com\/(watch\?|shorts\/|live\/)|youtu\.be\/)/.test(u);
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError("");

    if (!clip) {
      setError("Envie o arquivo do clipe viral.");
      return;
    }
    if (mode === "aligned" && !isValidYouTubeUrl(url.trim())) {
      setError("URL inválida do vídeo original. Use um link do YouTube.");
      return;
    }

    setBusy(true);
    try {
      const ref =
        mode === "aligned"
          ? await createReference(url.trim(), clip, sourceType)
          : await createStandaloneReference({
              clip,
              title: title.trim(),
              channel: channel.trim(),
              postUrl: postUrl.trim(),
              sourceType,
              notas: notas.trim(),
            });
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
        Envie um clipe que já viralizou (de outro criador). O ClipMint entende por que ele
        funcionou e passa a usar isso como referência ao cortar os seus.
      </p>

      {/* Modo */}
      <div className="flex gap-2 mb-5">
        <button
          type="button"
          onClick={() => setMode("standalone")}
          disabled={busy}
          className={`flex-1 rounded-lg px-4 py-3 text-left border transition-colors ${
            mode === "standalone"
              ? "bg-emerald-500/10 border-emerald-500 text-emerald-300"
              : "bg-gray-800 border-gray-700 text-gray-400 hover:bg-gray-700"
          }`}
        >
          <span className="block text-sm font-semibold">Só o clipe</span>
          <span className="block text-xs opacity-80 mt-0.5">
            Salvou do TikTok e não sabe de onde saiu
          </span>
        </button>
        <button
          type="button"
          onClick={() => setMode("aligned")}
          disabled={busy}
          className={`flex-1 rounded-lg px-4 py-3 text-left border transition-colors ${
            mode === "aligned"
              ? "bg-emerald-500/10 border-emerald-500 text-emerald-300"
              : "bg-gray-800 border-gray-700 text-gray-400 hover:bg-gray-700"
          }`}
        >
          <span className="block text-sm font-semibold">Clipe + vídeo original</span>
          <span className="block text-xs opacity-80 mt-0.5">
            Análise mais forte: vê o que ficou de fora
          </span>
        </button>
      </div>

      <form onSubmit={handleSubmit} className="flex flex-col gap-4">
        {mode === "aligned" && (
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
              className={FIELD}
            />
          </div>
        )}

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
              type="file"
              accept={ACCEPT}
              className="hidden"
              disabled={busy}
              onChange={(e) => setClip(e.target.files?.[0] ?? null)}
            />
          </label>
        </div>

        <div className="flex flex-col gap-2">
          <label className="text-sm font-medium text-gray-400">Conta que vai aprender com ele</label>
          <div className="flex gap-2">
            {NICHES.map((niche) => (
              <button
                key={niche.value}
                type="button"
                onClick={() => setSourceType(niche.value)}
                disabled={busy}
                className={`rounded-lg px-4 py-2 text-sm font-medium border transition-colors ${
                  sourceType === niche.value
                    ? "bg-emerald-500 border-emerald-500 text-white"
                    : "bg-gray-800 border-gray-700 text-gray-300 hover:bg-gray-700"
                }`}
              >
                {niche.label}
              </button>
            ))}
          </div>
        </div>

        {mode === "standalone" && (
          <>
            <div className="flex flex-col gap-2">
              <label htmlFor="ref-notas" className="text-sm font-medium text-gray-400">
                O que você já percebeu nesse clipe{" "}
                <span className="font-normal text-gray-600">
                  — opcional, mas entra na análise
                </span>
              </label>
              <textarea
                id="ref-notas"
                value={notas}
                onChange={(e) => setNotas(e.target.value)}
                rows={2}
                disabled={busy}
                placeholder="Ex: o texto na tela segura os 3 primeiros segundos, antes de a fala chegar."
                className={`${FIELD} resize-y`}
              />
            </div>

            <details className="group">
              <summary className="cursor-pointer text-sm text-gray-500 hover:text-gray-300 transition-colors select-none">
                Contexto opcional (título, criador, link do post)
              </summary>
              <div className="flex flex-col gap-3 mt-3">
                <input
                  type="text"
                  value={title}
                  onChange={(e) => setTitle(e.target.value)}
                  placeholder="Título ou assunto do clipe"
                  disabled={busy}
                  className={FIELD}
                />
                <input
                  type="text"
                  value={channel}
                  onChange={(e) => setChannel(e.target.value)}
                  placeholder="@ do criador"
                  disabled={busy}
                  className={FIELD}
                />
                <input
                  type="text"
                  value={postUrl}
                  onChange={(e) => setPostUrl(e.target.value)}
                  placeholder="Link do post (TikTok, Reels, Shorts)"
                  disabled={busy}
                  className={FIELD}
                />
              </div>
            </details>
          </>
        )}

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
