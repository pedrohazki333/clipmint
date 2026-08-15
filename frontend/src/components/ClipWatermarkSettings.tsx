"use client";
import type { SourceType } from "@/lib/types";

import { useEffect, useRef, useState } from "react";
import {
  deleteClipWatermark,
  getApiErrorMessage,
  getClipWatermarkUrl,
  hasClipWatermark,
  uploadClipWatermark,
} from "@/lib/api";

interface Props {
  /** Conta cujos presets estão sendo editados. */
  source: SourceType;
}

export default function ClipWatermarkSettings({ source }: Props) {
  const [configured, setConfigured] = useState<boolean | null>(null);
  const [cacheBust, setCacheBust] = useState(0);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const fileInputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    hasClipWatermark(source).then(setConfigured);
  }, [source]);

  async function handleFile(file: File | undefined) {
    if (!file) return;
    setBusy(true);
    setError("");
    try {
      await uploadClipWatermark(source, file);
      setConfigured(true);
      setCacheBust(Date.now());
    } catch (err) {
      setError(getApiErrorMessage(err, "Não foi possível enviar a imagem."));
    } finally {
      setBusy(false);
      if (fileInputRef.current) fileInputRef.current.value = "";
    }
  }

  async function handleRemove() {
    setBusy(true);
    setError("");
    try {
      await deleteClipWatermark(source);
      setConfigured(false);
    } catch (err) {
      setError(getApiErrorMessage(err, "Não foi possível remover."));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="rounded-2xl bg-gray-900 border border-gray-800 p-6">
      <div className="flex items-start justify-between gap-4">
        <div>
          <h2 className="text-base font-semibold text-gray-100">
            Marca d&apos;água do clipe
          </h2>
          <p className="text-sm text-gray-500 mt-1">
            Sua arte queimada no vídeo, centralizada sobre o gameplay, a 70% de
            opacidade. Só vale para clips em modo streamer.
          </p>
        </div>

        <div className="flex items-center gap-3 flex-shrink-0">
          {configured && (
            // Fundo quadriculado: sem ele, arte de borda clara sobre o card
            // escuro parece ter fundo próprio, e é a transparência que importa.
            // eslint-disable-next-line @next/next/no-img-element
            <img
              src={getClipWatermarkUrl(source, cacheBust)}
              alt="Marca d'água do clipe"
              className="h-12 w-12 object-contain rounded-lg border border-gray-700 p-1"
              style={{
                backgroundColor: "#1f2937",
                backgroundImage:
                  "linear-gradient(45deg,#374151 25%,transparent 25%,transparent 75%,#374151 75%)," +
                  "linear-gradient(45deg,#374151 25%,transparent 25%,transparent 75%,#374151 75%)",
                backgroundSize: "10px 10px",
                backgroundPosition: "0 0, 5px 5px",
              }}
            />
          )}
          <label
            className={`rounded-lg px-4 py-2 text-sm font-medium transition-colors cursor-pointer ${
              busy
                ? "bg-gray-800 text-gray-600 cursor-wait"
                : "bg-gray-800 hover:bg-gray-700 border border-gray-700 text-gray-300"
            }`}
          >
            {busy ? "Enviando..." : configured ? "Trocar" : "Enviar arte"}
            <input
              ref={fileInputRef}
              type="file"
              accept="image/png,image/jpeg,image/webp"
              className="hidden"
              disabled={busy}
              onChange={(e) => handleFile(e.target.files?.[0])}
            />
          </label>
          {configured && (
            <button
              onClick={handleRemove}
              disabled={busy}
              className="text-xs text-gray-500 hover:text-red-400 transition-colors disabled:opacity-50"
            >
              Remover
            </button>
          )}
        </div>
      </div>

      {configured === false && (
        <p className="mt-3 text-xs text-gray-500 bg-gray-800/40 rounded px-3 py-2">
          Sem arte aqui, os clips desta conta saem sem marca d&apos;água. É um
          arquivo separado da logo acima, que serve para cobrir QR code.
        </p>
      )}
      {error && (
        <p className="mt-3 text-xs text-red-400 bg-red-900/20 rounded px-3 py-2">{error}</p>
      )}
    </div>
  );
}
