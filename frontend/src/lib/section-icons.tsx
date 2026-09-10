import type { ReactNode } from "react";

/**
 * Os ícones que marcam cada bloco de configuração.
 *
 * Desenhados aqui, à mão, pelo mesmo motivo dos avatares (ver `lib/avatars.tsx`):
 * o projeto não carrega biblioteca de ícones, e três traços num `viewBox` de 24
 * custam menos que uma dependência inteira para nove símbolos.
 *
 * Eles não informam nada que o título já não diga — servem de âncora visual
 * para o olho achar de novo o bloco certo depois de rolar a página. Por isso
 * são `aria-hidden`: um leitor de tela que os anunciasse só repetiria o título.
 */

export type SectionIconName =
  | "identidade"
  | "icone"
  | "layout"
  | "legenda"
  | "marca"
  | "banner"
  | "faixa"
  | "formato"
  | "ajustes"
  | "previa"
  | "dica";

const PATHS: Record<SectionIconName, ReactNode> = {
  identidade: (
    <>
      <rect x="3" y="5" width="18" height="14" rx="2" />
      <path d="M7 9.5h5M7 13.5h8" />
    </>
  ),
  icone: (
    <>
      <circle cx="12" cy="12" r="9" />
      <path d="M9 10.5h.01M15 10.5h.01M8.5 14.5a4.5 4.5 0 0 0 7 0" />
    </>
  ),
  layout: (
    <>
      <rect x="4" y="2.5" width="16" height="19" rx="2" />
      <path d="M4 9h16M4 14h16" />
    </>
  ),
  legenda: (
    <>
      <rect x="2.5" y="5" width="19" height="14" rx="2" />
      <path d="M10 10.5a2.5 2.5 0 1 0 0 3M17 10.5a2.5 2.5 0 1 0 0 3" />
    </>
  ),
  marca: (
    <>
      <path d="M12 3s6 6.4 6 10a6 6 0 0 1-12 0c0-3.6 6-10 6-10z" />
    </>
  ),
  banner: (
    <>
      <rect x="3" y="8" width="18" height="8" rx="1.5" />
      <path d="M7.5 12h9" />
    </>
  ),
  faixa: (
    <>
      <rect x="2.5" y="9" width="19" height="6" rx="1.5" />
      <path d="M7 12h.01M12 12h.01M17 12h.01" />
    </>
  ),
  formato: (
    <>
      <rect x="2.5" y="5" width="19" height="14" rx="2" />
      <path d="M7.5 5v14M16.5 5v14" />
    </>
  ),
  ajustes: (
    <>
      <path d="M4 7h10M18 7h2M4 17h2M10 17h10" />
      <circle cx="16" cy="7" r="2" />
      <circle cx="8" cy="17" r="2" />
    </>
  ),
  previa: (
    <>
      <path d="M2.5 12S6 6.5 12 6.5 21.5 12 21.5 12 18 17.5 12 17.5 2.5 12 2.5 12z" />
      <circle cx="12" cy="12" r="2.5" />
    </>
  ),
  dica: (
    <>
      <path d="M9.5 18.5h5M10.5 21h3" />
      <path d="M12 3a6 6 0 0 0-3.5 10.9c.6.5 1 1.2 1 2h5c0-.8.4-1.5 1-2A6 6 0 0 0 12 3z" />
    </>
  ),
};

export function SectionIcon({
  name,
  className = "h-[18px] w-[18px]",
}: {
  name: SectionIconName;
  className?: string;
}) {
  return (
    <svg
      viewBox="0 0 24 24"
      className={className}
      fill="none"
      stroke="currentColor"
      strokeWidth="1.6"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      {PATHS[name]}
    </svg>
  );
}
