"use client";

import { useEffect, useRef, useState } from "react";
import {
  deleteWatermark,
  getApiErrorMessage,
  getWatermarkUrl,
  hasWatermark,
  uploadWatermark,
} from "@/lib/api";

export default function WatermarkSettings() {
  const [configured, setConfigured] = useState<boolean | null>(null);
  const [cacheBust, setCacheBust] = useState(0);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const fileInputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    hasWatermark().then(setConfigured);
  }, []);

  async function handleFile(file: File | undefined) {
    if (!file) return;
    setBusy(true);
    setError("");
    try {
      await uploadWatermark(file);
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
      await deleteWatermark();
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
          <h2 className="text-base font-semibold text-gray-100">Marca d&apos;água</h2>
          <p className="text-sm text-gray-500 mt-1">
            Sua logo cobre QR codes e marcas de terceiros nos clips, e assina a capa.
          </p>
        </div>

        <div className="flex items-center gap-3 flex-shrink-0">
          {configured && (
            // eslint-disable-next-line @next/next/no-img-element
            <img
              src={`${getWatermarkUrl()}?v=${cacheBust}`}
              alt="Marca d'água atual"
              className="h-12 w-12 object-contain rounded-lg bg-gray-800 border border-gray-700 p-1"
            />
          )}
          <label
            className={`rounded-lg px-4 py-2 text-sm font-medium transition-colors cursor-pointer ${
              busy
                ? "bg-gray-800 text-gray-600 cursor-wait"
                : "bg-gray-800 hover:bg-gray-700 border border-gray-700 text-gray-300"
            }`}
          >
            {busy ? "Enviando..." : configured ? "Trocar" : "Enviar logo"}
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
        <p className="mt-3 text-xs text-amber-500/80 bg-amber-900/15 rounded px-3 py-2">
          Sem logo configurada, QR codes detectados ainda são borrados — mas sua marca não aparece.
        </p>
      )}
      {error && (
        <p className="mt-3 text-xs text-red-400 bg-red-900/20 rounded px-3 py-2">{error}</p>
      )}
    </div>
  );
}
