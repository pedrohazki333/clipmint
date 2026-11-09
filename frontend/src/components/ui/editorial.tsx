import type { ReactNode } from "react";

/**
 * As peças editoriais que dão o ritmo de toda página: o marcador "///", o título
 * grande e o cabeçalho numerado das seções.
 *
 * Moram aqui para que "título de página" signifique a mesma coisa em todo lugar —
 * a direção visual vem da tipografia e da composição, e uma tipografia que cada
 * tela reinventa deixa de ser direção.
 */

/** "/// NOVO PROJETO" — o marcador em coral e o rótulo em caixa alta. */
export function Eyebrow({ children, className = "" }: { children: ReactNode; className?: string }) {
  return (
    <p
      className={`flex items-center gap-2.5 text-label font-bold uppercase tracking-[0.14em] text-ink ${className}`}
    >
      <span className="cm-slashes" aria-hidden />
      {children}
    </p>
  );
}

/**
 * O cabeçalho de página.
 *
 * `display` é o título condensado e enorme das páginas de ação ("GERAR CLIPES");
 * `page`, o título editorial das demais, menor e em Space Grotesk.
 */
export function PageHeader({
  eyebrow,
  title,
  description,
  actions,
  variant = "page",
  back,
}: {
  eyebrow?: ReactNode;
  title: ReactNode;
  description?: ReactNode;
  actions?: ReactNode;
  variant?: "display" | "page";
  /** Link de volta, acima do marcador. */
  back?: ReactNode;
}) {
  return (
    <header className="flex flex-col gap-5 sm:flex-row sm:items-end sm:justify-between">
      <div className="min-w-0">
        {back && <div className="mb-4">{back}</div>}
        {eyebrow && <Eyebrow className="mb-3">{eyebrow}</Eyebrow>}
        <h1
          className={
            variant === "display"
              ? "font-condensed text-[3.25rem] font-extrabold uppercase leading-[0.86] tracking-[-0.01em] text-ink sm:text-[4.25rem] xl:text-[5rem]"
              : "text-[2rem] font-bold leading-[1.05] text-ink sm:text-[2.5rem]"
          }
        >
          {title}
        </h1>
        {description && (
          <p className="mt-3 max-w-[34rem] text-[1.0625rem] leading-[1.45] text-ink-dim">
            {description}
          </p>
        )}
      </div>
      {actions && <div className="flex flex-shrink-0 flex-wrap gap-2">{actions}</div>}
    </header>
  );
}

/** "01  LINK DO VÍDEO" — o cabeçalho numerado de cada passo. */
export function StepHeader({
  number,
  title,
  aside,
  id,
}: {
  number: string;
  title: ReactNode;
  aside?: ReactNode;
  id?: string;
}) {
  return (
    <div className="flex items-baseline justify-between gap-3">
      <h2 id={id} className="flex items-baseline gap-4 font-display text-[0.9375rem] font-bold uppercase tracking-[0.08em] text-ink">
        <span className="tabular text-ink">{number}</span>
        <span>{title}</span>
      </h2>
      {aside}
    </div>
  );
}

/** "/// ÚLTIMOS PROJETOS" com a ação à direita — o rótulo de seção secundária. */
export function SectionLabel({
  children,
  action,
  id,
}: {
  children: ReactNode;
  action?: ReactNode;
  id?: string;
}) {
  return (
    <div className="flex items-center justify-between gap-3">
      <h2
        id={id}
        className="flex items-center gap-2.5 font-display text-[0.8125rem] font-bold uppercase tracking-[0.12em] text-ink"
      >
        <span className="cm-slashes" aria-hidden />
        {children}
      </h2>
      {action}
    </div>
  );
}

/**
 * As variantes de botão, como classes — e não como componente — porque o mesmo
 * visual vai em `<button>`, `<Link>` e `<a download>`.
 *
 *   - `create`: coral, a ação de criar. Texto branco só em 18px+ negrito.
 *   - `primary`: menta com texto escuro, a ação principal comum.
 *   - `secondary`: contorno em tinta, a alternativa.
 *   - `quiet`: sem moldura, para ações de apoio.
 */
export function buttonClass(
  variant: "create" | "primary" | "secondary" | "quiet" = "primary",
  size: "md" | "lg" = "md",
): string {
  const base =
    "inline-flex items-center justify-center gap-2 font-semibold transition-[background-color,border-color,color,opacity] duration-150 disabled:cursor-not-allowed disabled:opacity-45";
  const tamanho =
    size === "lg"
      ? "min-h-14 rounded-md px-6 text-[1.125rem] font-bold"
      : "min-h-10 rounded-md px-4 text-body";
  const cor = {
    create: "bg-coral text-white hover:bg-coral-strong",
    primary: "bg-mint-strong text-ink hover:bg-mint",
    secondary: "border border-ink/80 bg-transparent text-ink hover:bg-ink hover:text-base",
    quiet: "text-ink-dim hover:bg-inset hover:text-ink",
  }[variant];
  return `${base} ${tamanho} ${cor}`;
}
