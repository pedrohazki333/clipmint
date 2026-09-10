"use client";

import { useEffect, useMemo, useRef } from "react";

import { LinkButton } from "@/components/ui";
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
    <div className="flex flex-col gap-3">
      <div>
        <p className="text-body font-medium text-ink">Arte sobre o gameplay</p>
        <p className="mt-0.5 text-label leading-relaxed text-ink-muted">
          Sua assinatura sobre a imagem do jogo, a 70% de opacidade. Só aparece
          no layout facecam + gameplay.
        </p>
      </div>

      <div className="flex items-center gap-3">
        {mostrando ? (
          // eslint-disable-next-line @next/next/no-img-element
          <img
            src={mostrando}
            alt="Arte sobre o gameplay"
            className="h-14 w-14 flex-shrink-0 rounded-sm border border-line object-contain p-1.5"
            style={XADREZ}
          />
        ) : (
          <span
            className="flex h-14 w-14 flex-shrink-0 items-center justify-center rounded-sm border border-dashed border-line text-label text-ink-muted"
            style={XADREZ}
            aria-hidden="true"
          >
            —
          </span>
        )}

        <div className="flex flex-wrap items-center gap-x-4 gap-y-2">
          <label
            className={`cursor-pointer rounded-sm border border-line bg-inset px-4 py-2 text-body text-ink transition-colors hover:bg-hover ${
              disabled ? "pointer-events-none opacity-50" : ""
            }`}
          >
            {value.saved || value.file ? "Trocar arte" : "Enviar arte"}
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
            <LinkButton
              disabled={disabled}
              onClick={() => onChange({ ...value, file: null, remove: true })}
              className="hover:text-danger"
            >
              Remover
            </LinkButton>
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
        <p className="text-label leading-relaxed text-ink-muted">
          Sem arte aqui, o clipe sai sem nada sobre o gameplay.
        </p>
      )}
    </div>
  );
}
