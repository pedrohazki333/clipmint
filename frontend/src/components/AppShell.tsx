"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import type { ReactNode } from "react";

import { IS_PUBLIC_BUILD } from "@/lib/build";
import { ROTA_CADASTRO, ROTA_DASHBOARD } from "@/lib/rotas";
import CreditBalance from "@/components/CreditBalance";
import LogoutButton from "@/components/LogoutButton";
import UserMenu from "@/components/UserMenu";
import MarketingHeader from "@/components/marketing/MarketingHeader";

/**
 * Qual moldura a página recebe: a do produto ou a da vitrine.
 *
 * O ClipMint tem duas caras no mesmo domínio. Quem tem sessão vê a barra de
 * trabalho — saldo, conta, largura de ferramenta (896 px). Quem não tem, e está
 * numa das duas páginas abertas, vê a barra de marketing e uma página que vai
 * de borda a borda.
 *
 * A decisão mora AQUI e só aqui. A alternativa seria cada página montar o seu
 * cabeçalho, e aí existiriam duas implementações do estado de autenticação para
 * manter em sincronia — a segunda envelheceria em silêncio.
 *
 * `loggedIn` vem do servidor (o layout lê o cookie); o caminho vem do cliente.
 * Nenhum dos dois é decisão de segurança: quem autoriza de verdade é o
 * middleware e, atrás dele, o backend. Isto só escolhe o que desenhar.
 */

/** Páginas abertas a visitante — as mesmas de MARKETING_PATHS no middleware. */
const PAGINAS_DE_VITRINE = new Set(["/", "/como-funciona"]);

/** A largura e o respiro de todas as telas do produto. */
const MOLDURA_DO_APP = "mx-auto max-w-4xl px-4 py-6 sm:px-6 sm:py-8";

export default function AppShell({
  loggedIn,
  children,
}: {
  loggedIn: boolean;
  children: ReactNode;
}) {
  const pathname = usePathname();
  const vitrine =
    IS_PUBLIC_BUILD && !loggedIn && PAGINAS_DE_VITRINE.has(pathname);

  if (vitrine) {
    const landing = pathname === "/";
    return (
      <>
        <MarketingHeader largura={landing ? "landing" : "app"} />
        {/* Só a landing solta a largura: ela tem composições que não cabem em
            896 px. O tutorial continua na medida do produto — é texto, e texto
            largo é texto que ninguém lê. */}
        <main className={landing ? undefined : MOLDURA_DO_APP}>{children}</main>
      </>
    );
  }

  return (
    <>
      <AppHeader loggedIn={loggedIn} />
      <main className={MOLDURA_DO_APP}>{children}</main>
    </>
  );
}

/**
 * O cabeçalho do produto — o mesmo de sempre, agora com endereço próprio.
 *
 * O saldo vem ANTES da conta porque é o que se consulta com frequência: a conta
 * se abre uma vez por semana.
 */
function AppHeader({ loggedIn }: { loggedIn: boolean }) {
  return (
    <header className="border-b border-line px-4 py-4 sm:px-6">
      <div className="mx-auto flex max-w-4xl items-center gap-3">
        {/* Logado, a marca leva ao produto; deslogado (build pessoal antes da
            senha), à raiz. A landing tem a barra dela. */}
        <Link
          href={loggedIn ? ROTA_DASHBOARD : "/"}
          className="text-title font-semibold text-mint"
        >
          ClipMint
        </Link>
        <span className="hidden text-label text-ink-muted sm:inline">
          cortes verticais a partir de vídeos longos
        </span>
        {/* Só existe landing e tutorial no build público — a versão pessoal não
            ganha este link, pois nunca mostra a landing. */}
        {IS_PUBLIC_BUILD && (
          <Link
            href="/como-funciona"
            className="text-label text-ink-dim transition-colors hover:text-ink"
          >
            Como usar
          </Link>
        )}
        {/* Público: saldo sempre à vista + botão de conta, ou CTA de cadastro
            para quem ainda não entrou. Pessoal: não há conta nem crédito, só a
            porta de saída da senha única. */}
        <div className="ml-auto flex items-center gap-2">
          {loggedIn ? (
            <>
              {IS_PUBLIC_BUILD && <CreditBalance />}
              {IS_PUBLIC_BUILD ? <UserMenu /> : <LogoutButton />}
            </>
          ) : (
            IS_PUBLIC_BUILD && (
              <Link
                href={ROTA_CADASTRO}
                className="rounded-sm bg-mint-strong px-3 py-1.5 text-label font-medium text-on-mint transition-colors hover:bg-mint"
              >
                Criar conta
              </Link>
            )
          )}
        </div>
      </div>
    </header>
  );
}
