"use client";

import { useEffect, useMemo, useRef } from "react";

import type { FileSlot } from "@/lib/brand";

/**
 * A logo que cobre QR code e assina a capa.
 *
 * Campo CONTROLADO: não fala com a API. Quem grava é o `applyBrandDraft` do
 * formulário, no submit — é isso que permite configurar a marca já na criação
 * do perfil, antes de existir um id para nomear a pasta dos presets.
 */
interface Props {
  value: FileSlot;
  onChange: (v: FileSlot) => void;
  /** Imagem já gravada. Só existe na edição. */
  savedUrl?: string;
  disabled?: boolean;
}

export default function WatermarkSettings({
  value,
  onChange,
  savedUrl,
  disabled = false,
}: Props) {
  const inputRef = useRef<HTMLInputElement>(null);

  // A prévia do arquivo escolhido vive só no navegador até o submit.
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
          <p className="text-body font-medium text-ink">Marca d&apos;água</p>
          <p className="mt-1 text-label text-ink-muted">
            Sua logo cobre QR codes e marcas de terceiros nos clipes, e assina a
            capa.
          </p>
        </div>

        <div className="flex flex-shrink-0 items-center gap-3">
          {mostrando ? (
            // eslint-disable-next-line @next/next/no-img-element
            <img
              src={mostrando}
              alt="Marca d'água"
              className="h-12 w-12 rounded-sm border border-line bg-inset object-contain p-1"
            />
          ) : (
            // Exemplo apagado: nada desta imagem entra no clipe.
            // eslint-disable-next-line @next/next/no-img-element
            <img
              src="/marca-clipmint.png"
              alt="Exemplo de marca d'água"
              title="Exemplo — envie a sua para substituir"
              className="h-12 w-20 rounded-sm border border-dashed border-line bg-inset object-contain p-1 opacity-40"
            />
          )}
          <label
            className={`cursor-pointer rounded-sm border border-line bg-inset px-4 py-2 text-body text-ink transition-colors hover:bg-hover ${
              disabled ? "pointer-events-none opacity-50" : ""
            }`}
          >
            {value.saved || value.file ? "Trocar" : "Enviar logo"}
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
          A logo sai ao salvar.
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
    </div>
  );
}
