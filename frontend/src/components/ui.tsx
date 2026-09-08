"use client";

import { useId, useState, type ReactNode } from "react";

/**
 * As peças que o produto repete.
 *
 * O levantamento de 04/09 contou o mesmo card escrito à mão em ~20 lugares, o
 * mesmo botão primário em ~12 (metade com `text-base`, metade com `text-white`)
 * e a mesma faixa de erro em 9. Cada cópia é uma chance de divergir, e várias já
 * tinham divergido. Daqui para frente a aparência de um botão muda num arquivo.
 *
 * Mesmos tokens de sempre — isto não é um sistema novo, é o que já existia,
 * escrito uma vez só.
 */

/* ── Superfície ─────────────────────────────────────────────────────────── */

export function Card({
  children,
  className = "",
}: {
  children: ReactNode;
  className?: string;
}) {
  return (
    <div className={`rounded-md border border-line bg-raised p-4 sm:p-6 ${className}`}>
      {children}
    </div>
  );
}

/* ── Botões ─────────────────────────────────────────────────────────────── */

type Variante = "primario" | "secundario" | "fantasma";

const ESTILO: Record<Variante, string> = {
  // `text-on-mint` e não `text-base`: o Tailwind resolve `text-*` primeiro como
  // tamanho, e foi por isso que as cópias antigas divergiram.
  primario:
    "bg-mint-strong text-on-mint hover:bg-mint disabled:opacity-50 disabled:cursor-not-allowed",
  secundario:
    "border border-line text-ink hover:border-line-strong hover:bg-hover disabled:opacity-50",
  fantasma: "text-ink-dim hover:text-ink",
};

export function Button({
  variante = "primario",
  className = "",
  ...props
}: React.ButtonHTMLAttributes<HTMLButtonElement> & { variante?: Variante }) {
  return (
    <button
      {...props}
      className={`inline-flex items-center justify-center rounded-sm px-5 py-2.5 text-body font-medium transition-colors ${ESTILO[variante]} ${className}`}
    />
  );
}

/* ── Ajuda ──────────────────────────────────────────────────────────────── */

/**
 * A explicação de um campo, sob demanda.
 *
 * Botão de verdade, aberto por clique ou teclado — não por `hover`. No celular
 * hover não existe, e metade dos campos deste produto são configurados no
 * celular. Também não é `title`: o balão nativo não aparece no toque e não é
 * lido por leitor de tela de forma confiável.
 *
 * Abre no lugar, empurrando o conteúdo, em vez de flutuar por cima: um balão
 * posicionado em cima de uma tela estreita sempre acaba cortado por alguma
 * borda, e consertar isso pede medir a viewport a cada abertura.
 */
export function Hint({ children, label = "O que é isso?" }: { children: ReactNode; label?: string }) {
  const [aberto, setAberto] = useState(false);
  const id = useId();

  return (
    <>
      <button
        type="button"
        onClick={() => setAberto((v) => !v)}
        aria-expanded={aberto}
        aria-controls={id}
        aria-label={label}
        className={`inline-flex h-5 w-5 flex-shrink-0 items-center justify-center rounded-full border text-[11px] font-semibold transition-colors ${
          aberto
            ? "border-mint bg-mint-soft text-mint"
            : "border-line bg-inset text-ink-dim hover:border-line-strong hover:text-ink"
        }`}
      >
        ?
      </button>
      {aberto && (
        <p
          id={id}
          className="mt-2 w-full rounded-sm border-l-2 border-mint bg-inset px-3 py-2 text-label leading-relaxed text-ink-dim"
        >
          {children}
        </p>
      )}
    </>
  );
}

/* ── Campo ──────────────────────────────────────────────────────────────── */

/**
 * Rótulo, ajuda opcional, controle e erro — nesta ordem, sempre.
 *
 * A ajuda mora ao lado do rótulo e não embaixo do campo: quem está decidindo o
 * que preencher olha para o rótulo, não para o rodapé.
 */
export function Field({
  label,
  htmlFor,
  hint,
  erro,
  children,
}: {
  label: string;
  htmlFor?: string;
  hint?: ReactNode;
  erro?: string;
  children: ReactNode;
}) {
  return (
    <div className="flex flex-col gap-2">
      <div className="flex flex-wrap items-center gap-2">
        <label htmlFor={htmlFor} className="text-body font-medium text-ink">
          {label}
        </label>
        {hint && <Hint>{hint}</Hint>}
      </div>
      {children}
      {erro && (
        <p role="alert" className="text-label text-danger">
          {erro}
        </p>
      )}
    </div>
  );
}

/** O campo de texto padrão do produto. */
export function Input(props: React.InputHTMLAttributes<HTMLInputElement>) {
  return (
    <input
      {...props}
      className={`w-full rounded-sm border border-line bg-inset px-4 py-2.5 text-body text-ink placeholder-ink-dim outline-none transition-colors focus:border-mint disabled:opacity-50 ${props.className ?? ""}`}
    />
  );
}

/* ── Faixa de erro ──────────────────────────────────────────────────────── */

export function ErroFaixa({ children }: { children: ReactNode }) {
  return (
    <p
      role="alert"
      className="rounded-sm border border-danger/40 bg-danger-soft px-3 py-2 text-body text-danger"
    >
      {children}
    </p>
  );
}
