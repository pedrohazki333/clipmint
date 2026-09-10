"use client";

import { useId } from "react";

import { MiniField } from "@/components/ui";

export const HEX_RE = /^#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{6})$/;

/** Expande #RGB para #RRGGBB (input type=color só aceita 6 dígitos). */
export function toFullHex(value: string, fallback: string): string {
  if (!HEX_RE.test(value)) return fallback;
  const v = value.slice(1);
  const full = v.length === 3 ? v.split("").map((c) => c + c).join("") : v;
  return `#${full.toUpperCase()}`;
}

interface Props {
  label: string;
  value: string;
  onChange: (v: string) => void;
  disabled: boolean;
  fallback: string;
}

/**
 * Par seletor de cor + campo hexadecimal.
 *
 * Rótulo em cima e o par embaixo, ocupando a largura toda da célula: em fileira
 * — rótulo, amostra e poço lado a lado — o campo de texto era o único que podia
 * encolher, e num celular estreito ele chegava a cortar o próprio `#RRGGBB`.
 *
 * A amostra é um `input type=color` de verdade, e não um botão que abre um
 * seletor nosso: o do sistema já é o que a pessoa conhece, funciona no toque e
 * vem de graça com acessibilidade.
 */
export default function ColorField({ label, value, onChange, disabled, fallback }: Props) {
  const valid = HEX_RE.test(value);
  const id = useId();

  return (
    <MiniField label={label} htmlFor={id}>
      <div
        className={`flex items-center gap-2 rounded-sm border bg-inset px-2 py-1.5 transition-colors focus-within:border-mint ${
          valid ? "border-line" : "border-danger"
        } ${disabled ? "opacity-50" : ""}`}
      >
        <input
          type="color"
          aria-label={`${label}: seletor de cor`}
          value={toFullHex(value, fallback)}
          disabled={disabled}
          onChange={(e) => onChange(e.target.value.toUpperCase())}
          className="h-6 w-6 flex-shrink-0 cursor-pointer rounded border border-line bg-transparent p-0 disabled:cursor-not-allowed"
        />
        <input
          id={id}
          type="text"
          value={value}
          disabled={disabled}
          onChange={(e) => onChange(e.target.value)}
          placeholder="#RRGGBB"
          maxLength={7}
          spellCheck={false}
          className="w-full min-w-0 bg-transparent font-mono text-body uppercase text-ink outline-none placeholder:normal-case placeholder:text-ink-muted"
        />
      </div>
    </MiniField>
  );
}
