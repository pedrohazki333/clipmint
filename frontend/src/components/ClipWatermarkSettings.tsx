"use client";

import { useEffect, useMemo, useRef } from "react";

import type { FileSlot } from "@/lib/brand";

/**
 * A arte queimada no clipe — a assinatura da conta.
 *
 * Arquivo separado da marca d'água de propósito: aquela é escolhida para TAPAR
 * uma área (QR code), esta para ser vista. Campo controlado, como os outros:
 * quem grava é o submit do formulário.
 */
interface Props {
  value: FileSlot;
  onChange: (v: FileSlot) => void;
  savedUrl?: string;
  disabled?: boolean;
}

/** Xadrez atrás da prévia: sem ele, arte de borda clara parece ter fundo. */
const XADREZ = {
  backgroundColor: "#1f2937",
  backgroundImage:
    "linear-gradient(45deg,#374151 25%,transparent 25%,transparent 75%,#374151 75%)," +
    "linear-gradient(45deg,#374151 25%,transparent 25%,transparent 75%,#374151 75%)",
  backgroundSize: "10px 10px",
  backgroundPosition: "0 0, 5px 5px",
} as const;

export default function ClipWatermarkSettings({
  value,
  onChange,
  savedUrl,
  disabled = false,
}: Props) {
  const inputRef = useRef<HTMLInputElement>(null);

  const localUrl = useMemo(
    () => (value.file ? URL.createObjectURL(value.file) : null),
    [value.file],
  );
  useEffect(() => {
    return () => {
      if (localUrl) URL.revokeObjectURL(localUrl);
    };
  }, [localUrl]);

  const mostrando = localUrl ?? (value.saved && !value.remove ? savedUrl : null);

  return (
    <div className="flex flex-col gap-2">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div className="min-w-0">
          <p className="text-body font-medium text-ink">
            Marca d&apos;água do clipe
          </p>
          <p className="mt-1 text-label text-ink-muted">
            Sua arte sobre o gameplay, a 70% de opacidade. Só vale para clipes em
            modo streamer.
          </p>
        </div>

        <div className="flex flex-shrink-0 items-center gap-3">
          {mostrando && (
            // eslint-disable-next-line @next/next/no-img-element
            <img
              src={mostrando}
              alt="Marca d'água do clipe"
              className="h-12 w-12 rounded-sm border border-line object-contain p-1"
              style={XADREZ}
            />
          )}
          <label
            className={`cursor-pointer rounded-sm border border-line bg-inset px-4 py-2 text-body text-ink transition-colors hover:bg-hover ${
              disabled ? "pointer-events-none opacity-50" : ""
            }`}
          >
            {value.saved || value.file ? "Trocar" : "Enviar arte"}
            <input
              ref={inputRef}
              type="file"
              accept="image/png,image/jpeg,image/webp"
              className="hidden"
              disabled={disabled}
              onChange={(e) => {
                const file = e.target.files?.[0];
                if (file) onChange({ ...value, file, remove: false });
                if (inputRef.current) inputRef.current.value = "";
              }}
            />
          </label>
          {(value.file || (value.saved && !value.remove)) && (
            <button
              type="button"
              disabled={disabled}
              onClick={() => onChange({ ...value, file: null, remove: true })}
              className="text-label text-ink-dim transition-colors hover:text-danger disabled:opacity-50"
            >
              Remover
            </button>
          )}
        </div>
      </div>

      {value.remove && value.saved && (
        <p className="flex items-center gap-3 rounded-sm bg-inset px-3 py-2 text-label text-ink-dim">
          A arte sai ao salvar.
          <button
            type="button"
            onClick={() => onChange({ ...value, remove: false })}
            className="text-mint transition-colors hover:text-mint-strong"
          >
            Desfazer
          </button>
        </p>
      )}
      {value.file && (
        <p className="rounded-sm bg-inset px-3 py-2 text-label text-ink-dim">
          {value.file.name} — enviada ao salvar.
        </p>
      )}
      {!value.saved && !value.file && (
        <p className="rounded-sm bg-inset px-3 py-2 text-label text-ink-muted">
          Sem arte aqui, o clipe sai sem marca d&apos;água.
        </p>
      )}
    </div>
  );
}
