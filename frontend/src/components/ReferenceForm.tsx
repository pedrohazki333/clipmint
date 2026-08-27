"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import type { SourceType } from "@/lib/types";
import { PUBLIC_NICHES } from "@/lib/features";
import { PERSONAL_NICHES } from "@/personal/data";
import { getApiErrorMessage } from "@/lib/api";
import { createReference, createStandaloneReference } from "@/personal/learning-api";

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

// Os nichos deste build (ver src/lib/features.ts).
const NICHES = [...PUBLIC_NICHES, ...PERSONAL_NICHES];

const FIELD =
  "w-full rounded-sm bg-inset border border-line px-4 py-3 text-ink placeholder-ink-muted focus:outline-none focus:border-mint disabled:opacity-50";

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
    <div className="rounded-md bg-raised border border-line p-6">
      <h2 className="text-body font-semibold text-ink">Aprender com clipe viral</h2>
      <p className="text-body text-ink-dim mt-1 mb-5">
        Envie um clipe que já viralizou (de outro criador). O ClipMint entende por que ele
        funcionou e passa a usar isso como referência ao cortar os seus.
      </p>

      {/* Modo */}
      <div className="flex gap-2 mb-5">
        <button
          type="button"
          onClick={() => setMode("standalone")}
          disabled={busy}
          className={`flex-1 rounded-sm px-4 py-3 text-left border transition-colors ${
            mode === "standalone"
              ? "bg-mint-soft border-mint text-mint"
              : "bg-inset border-line text-ink-dim hover:bg-hover"
          }`}
        >
          <span className="block text-body font-semibold">Só o clipe</span>
          <span className="block text-label opacity-80 mt-0.5">
            Salvou do TikTok e não sabe de onde saiu
          </span>
        </button>
        <button
          type="button"
          onClick={() => setMode("aligned")}
          disabled={busy}
          className={`flex-1 rounded-sm px-4 py-3 text-left border transition-colors ${
            mode === "aligned"
              ? "bg-mint-soft border-mint text-mint"
              : "bg-inset border-line text-ink-dim hover:bg-hover"
          }`}
        >
          <span className="block text-body font-semibold">Clipe + vídeo original</span>
          <span className="block text-label opacity-80 mt-0.5">
            Análise mais forte: vê o que ficou de fora
          </span>
        </button>
      </div>

      <form onSubmit={handleSubmit} className="flex flex-col gap-4">
        {mode === "aligned" && (
          <div className="flex flex-col gap-2">
            <label htmlFor="ref-url" className="text-body font-medium text-ink-dim">
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
          <label className="text-body font-medium text-ink-dim">Arquivo do clipe viral</label>
          <label
            className={`flex items-center justify-between gap-3 rounded-sm border border-dashed px-4 py-3 cursor-pointer transition-colors ${
              busy
                ? "border-line cursor-wait"
                : "border-line hover:border-mint/60 bg-inset"
            }`}
          >
            <span className={`text-body truncate ${clip ? "text-ink" : "text-ink-dim"}`}>
              {clip ? clip.name : "Escolher arquivo de vídeo (mp4, mov, webm...)"}
            </span>
            <span className="text-label text-ink-dim flex-shrink-0 rounded-md bg-inset border border-line px-3 py-1.5">
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
          <label className="text-body font-medium text-ink-dim">Conta que vai aprender com ele</label>
          <div className="flex gap-2">
            {NICHES.map((niche) => (
              <button
                key={niche.source}
                type="button"
                onClick={() => setSourceType(niche.source)}
                disabled={busy}
                className={`rounded-sm px-4 py-2 text-body font-medium border transition-colors ${
                  sourceType === niche.source
                    ? "bg-mint-strong border-mint text-white"
                    : "bg-inset border-line text-ink hover:bg-hover"
                }`}
              >
                {niche.title}
              </button>
            ))}
          </div>
        </div>

        {mode === "standalone" && (
          <>
            <div className="flex flex-col gap-2">
              <label htmlFor="ref-notas" className="text-body font-medium text-ink-dim">
                O que você já percebeu nesse clipe{" "}
                <span className="font-normal text-ink-muted">
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
              <summary className="cursor-pointer text-body text-ink-dim hover:text-ink transition-colors select-none">
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
          <p className="text-body text-danger bg-danger-soft rounded px-3 py-2">{error}</p>
        )}

        <button
          type="submit"
          disabled={busy}
          className="w-full rounded-sm bg-mint-strong hover:bg-mint disabled:bg-inset disabled:cursor-not-allowed px-6 py-3 font-semibold text-white transition-colors"
        >
          {busy ? "Enviando..." : "Analisar e aprender"}
        </button>
      </form>
    </div>
  );
}
