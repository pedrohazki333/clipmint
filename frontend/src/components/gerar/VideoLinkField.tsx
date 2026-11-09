"use client";

import { useEffect, useState } from "react";
import { ClipboardPaste, X } from "lucide-react";

/** O "play" vermelho que todo mundo lê como "link do YouTube". */
function MarcaYouTube() {
  return (
    <svg viewBox="0 0 28 20" className="h-5 w-7 flex-shrink-0" aria-hidden focusable="false">
      <rect width="28" height="20" rx="5.5" fill="#FF0000" />
      <path d="M11.2 6v8l7-4z" fill="#fff" />
    </svg>
  );
}

export default function VideoLinkField({
  value,
  onChange,
  error,
  disabled,
  labelledBy,
}: {
  value: string;
  onChange: (value: string) => void;
  error?: string;
  disabled?: boolean;
  labelledBy: string;
}) {
  // Ler a área de transferência é permissão do navegador: o Firefox não deixa e
  // o Safari pergunta. Onde não existe, o botão nem aparece — colar à mão segue.
  const [podeColar, setPodeColar] = useState(false);
  useEffect(() => {
    setPodeColar(typeof navigator !== "undefined" && !!navigator.clipboard?.readText);
  }, []);

  async function colar() {
    try {
      const texto = (await navigator.clipboard.readText()).trim();
      if (texto) onChange(texto);
    } catch {
      // Negado pela pessoa ou pelo navegador: o campo continua aceitando Ctrl+V.
      setPodeColar(false);
    }
  }

  return (
    <div>
      <div
        className={`flex min-h-12 items-center gap-3 rounded-md border bg-raised pl-4 pr-1.5 transition-[border-color,box-shadow] duration-150 focus-within:border-ink focus-within:shadow-[0_0_0_1px_var(--color-ink)] ${
          error ? "border-danger" : "border-line hover:border-line-strong"
        }`}
      >
        <MarcaYouTube />
        <input
          id="cm-url"
          type="url"
          inputMode="url"
          autoComplete="off"
          spellCheck={false}
          value={value}
          onChange={(e) => onChange(e.target.value)}
          placeholder="Cole o link do YouTube aqui..."
          disabled={disabled}
          aria-labelledby={labelledBy}
          aria-invalid={!!error}
          aria-describedby={error ? "cm-url-erro" : undefined}
          className="min-w-0 flex-1 bg-transparent py-2.5 text-[0.9375rem] text-ink placeholder:text-ink-muted focus:outline-none focus-visible:outline-none disabled:opacity-50"
        />
        {value && !disabled && (
          <button
            type="button"
            onClick={() => onChange("")}
            className="flex h-10 w-10 items-center justify-center rounded-md text-ink-muted transition-colors hover:bg-inset hover:text-ink"
          >
            <X className="h-4 w-4" aria-hidden />
            <span className="sr-only">Limpar link</span>
          </button>
        )}
        {podeColar && !value && (
          <button
            type="button"
            onClick={colar}
            disabled={disabled}
            className="flex h-10 items-center gap-2 rounded-md px-3 text-body font-medium text-ink-dim transition-colors hover:bg-inset hover:text-ink"
          >
            <ClipboardPaste className="h-[1.125rem] w-[1.125rem]" aria-hidden />
            <span className="hidden sm:inline">Colar</span>
            <span className="sr-only sm:hidden">Colar link</span>
          </button>
        )}
      </div>
      {error && (
        <p id="cm-url-erro" role="alert" className="mt-2 text-body text-danger">
          {error}
        </p>
      )}
    </div>
  );
}
