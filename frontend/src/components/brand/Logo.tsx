/**
 * A marca do ClipMint: o "play" num círculo e o nome ao lado.
 *
 * É o mesmo desenho de `public/marca-clipmint.png`, redesenhado em SVG para as
 * cores novas — o PNG traz o fundo escuro e o verde antigo assados nele, e não
 * acompanharia a navegação nem um fundo claro. O círculo fica em menta (a cor de
 * identidade) e ganha um corte em coral (a cor de criação), como na referência.
 *
 * `tone` decide a cor do "Clip": claro sobre a navegação escura, tinta sobre o
 * papel. O "Mint" fica em menta só sobre fundo escuro — sobre o claro ela não
 * passa de 1,4:1, e então vira tinta também, e a menta fica só no símbolo.
 */
export function LogoMark({ className = "h-8 w-8" }: { className?: string }) {
  return (
    <svg viewBox="0 0 32 32" className={className} aria-hidden focusable="false">
      <circle cx="16" cy="16" r="15" fill="var(--color-mint-strong)" />
      <path
        d="M16 1a15 15 0 0 1 0 30"
        fill="none"
        stroke="var(--color-coral)"
        strokeWidth="2"
        strokeLinecap="round"
      />
      <path d="M12.5 9.6v12.8c0 .9 1 1.4 1.7.9l9.4-6.4c.6-.4.6-1.4 0-1.8l-9.4-6.4c-.7-.5-1.7 0-1.7.9Z" fill="#242424" />
    </svg>
  );
}

export default function Logo({
  tone = "dark",
  className = "",
}: {
  /** "dark" = sobre a navegação escura; "light" = sobre o papel claro. */
  tone?: "dark" | "light";
  className?: string;
}) {
  const clip = tone === "dark" ? "text-sidebar-text" : "text-ink";
  const mint = tone === "dark" ? "text-mint-strong" : "text-ink";
  return (
    <span className={`inline-flex items-center gap-2.5 ${className}`}>
      <LogoMark />
      <span className="font-display text-[1.375rem] font-bold leading-none tracking-[-0.03em]">
        <span className={clip}>Clip</span>
        <span className={mint}>Mint</span>
      </span>
    </span>
  );
}
