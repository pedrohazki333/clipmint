import Link from "next/link";
import type { ReactNode } from "react";

/**
 * As peças que se repetem na landing — e só as que se repetem.
 *
 * O app tem `max-w-4xl` (896 px) em todas as telas, largura de ferramenta. A
 * landing usa 1152: ela tem composições que não cabem em 896 sem virar coluna
 * estreita, e é a única página do produto assim. O resto (cor, raio, foco,
 * fonte) é o mesmo sistema — não há paleta nova aqui.
 *
 * Uma regra vale para a landing inteira: o texto dela usa `ink` e `ink-dim`,
 * nunca `ink-muted`. O muted mede 4,29:1 sobre o fundo, logo abaixo dos 4,5 que
 * um texto pequeno precisa; o dim mede 7,3:1 e continua sendo o segundo nível
 * do sistema, então a hierarquia é a mesma e só a leitura melhora. A exceção
 * são as réplicas de tela em `mocks.tsx`: ali o muted é o que o app usa de
 * verdade, e trocá-lo faria a réplica mentir sobre a tela real.
 */

export function Container({
  children,
  className = "",
}: {
  children: ReactNode;
  className?: string;
}) {
  return (
    <div className={`mx-auto w-full max-w-6xl px-5 sm:px-8 ${className}`}>
      {children}
    </div>
  );
}

/**
 * Rótulo curto acima do título. Mono e espaçado para ler como marcação de
 * seção, não como uma frase que ficou pequena.
 */
export function Eyebrow({ children }: { children: ReactNode }) {
  return (
    <p className="font-mono text-label uppercase tracking-[0.18em] text-mint">
      {children}
    </p>
  );
}

export function SectionTitle({
  children,
  className = "",
}: {
  children: ReactNode;
  className?: string;
}) {
  return (
    <h2 className={`text-section font-semibold text-ink ${className}`}>
      {children}
    </h2>
  );
}

/**
 * O CTA principal. Existe em dois lugares na página inteira (hero e CTA final)
 * mais a navbar — de propósito: a landing convence pelo que mostra, não por
 * repetir o botão depois de cada seção.
 */
export function CtaPrimary({
  href,
  children,
  className = "",
}: {
  href: string;
  children: ReactNode;
  className?: string;
}) {
  return (
    <Link
      href={href}
      className={`inline-flex items-center justify-center rounded-sm bg-mint-strong px-6 py-3 text-body font-semibold text-on-mint transition-colors hover:bg-mint ${className}`}
    >
      {children}
    </Link>
  );
}

export function CtaSecondary({
  href,
  children,
  className = "",
}: {
  href: string;
  children: ReactNode;
  className?: string;
}) {
  return (
    <Link
      href={href}
      className={`inline-flex items-center justify-center rounded-sm border border-line px-6 py-3 text-body font-medium text-ink transition-colors hover:border-line-strong hover:bg-raised ${className}`}
    >
      {children}
    </Link>
  );
}
