"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useRef, useState } from "react";
import { Menu, X } from "lucide-react";

import Logo from "@/components/brand/Logo";
import Sidebar from "@/components/shell/Sidebar";

/** Telas de entrada: sem navegação, só a marca e o formulário. */
const TELAS_DE_ENTRADA = new Set(["/login", "/esqueci-senha", "/redefinir-senha"]);
/** O que a landing do build público ocupa. Fica no tema antigo até ser refeita. */
const MARKETING = new Set(["/", "/como-funciona"]);
/**
 * Rotas que desenham a própria grade de ponta a ponta. As demais ganham a
 * coluna de leitura padrão.
 */
const SANGRIA_TOTAL = new Set(["/gerar"]);

/**
 * A moldura do app, decidida pela rota.
 *
 *   - logado → navegação escura fixa à esquerda (no celular, barra no topo e
 *     gaveta) e a área de trabalho clara;
 *   - tela de entrada → só a marca;
 *   - landing pública sem login → o cabeçalho e o tema antigos, intactos.
 *
 * Decidido no cliente porque o layout raiz do App Router não recebe a rota. O
 * que chega do servidor é só se há sessão, e isso não muda sem recarregar.
 */
export default function Chrome({
  loggedIn,
  publicBuild,
  children,
}: {
  loggedIn: boolean;
  publicBuild: boolean;
  children: React.ReactNode;
}) {
  const pathname = usePathname() ?? "/";

  if (TELAS_DE_ENTRADA.has(pathname)) {
    return (
      <div className="min-h-screen bg-base">
        <header className="px-5 pt-6 sm:px-10 sm:pt-8">
          <Logo tone="light" />
        </header>
        <main className="mx-auto max-w-md px-5 pb-16 sm:px-6">{children}</main>
      </div>
    );
  }

  if (!loggedIn && publicBuild && MARKETING.has(pathname)) {
    return <LegacyMarketingChrome>{children}</LegacyMarketingChrome>;
  }

  return <AppShell pathname={pathname}>{children}</AppShell>;
}

function AppShell({ pathname, children }: { pathname: string; children: React.ReactNode }) {
  const [aberta, setAberta] = useState(false);
  const botaoRef = useRef<HTMLButtonElement>(null);

  // A gaveta fecha ao navegar e com Esc, e devolve o foco a quem a abriu.
  useEffect(() => setAberta(false), [pathname]);
  useEffect(() => {
    if (!aberta) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        setAberta(false);
        botaoRef.current?.focus();
      }
    };
    document.addEventListener("keydown", onKey);
    document.body.style.overflow = "hidden";
    return () => {
      document.removeEventListener("keydown", onKey);
      document.body.style.overflow = "";
    };
  }, [aberta]);

  const sangria = SANGRIA_TOTAL.has(pathname);

  return (
    <div className="min-h-screen bg-base">
      {/* Desktop: navegação fixa */}
      <aside className="fixed inset-y-0 left-0 z-30 hidden w-[15rem] lg:block">
        <Sidebar />
      </aside>

      {/* Celular e tablet: barra no topo + gaveta */}
      <header className="cm-on-dark sticky top-0 z-30 flex h-14 items-center justify-between bg-sidebar px-4 lg:hidden">
        <Link href="/gerar" aria-label="ClipMint — gerar clipes">
          <Logo tone="dark" />
        </Link>
        <button
          ref={botaoRef}
          type="button"
          onClick={() => setAberta(true)}
          aria-expanded={aberta}
          aria-controls="cm-gaveta"
          className="-mr-2 flex h-10 w-10 items-center justify-center rounded-md text-sidebar-text hover:bg-sidebar-raised"
        >
          <Menu className="h-5 w-5" aria-hidden />
          <span className="sr-only">Abrir menu</span>
        </button>
      </header>

      {aberta && (
        <div className="fixed inset-0 z-40 lg:hidden" role="dialog" aria-modal="true" aria-label="Menu" id="cm-gaveta">
          <button
            type="button"
            aria-label="Fechar menu"
            className="absolute inset-0 bg-ink/50"
            onClick={() => setAberta(false)}
          />
          <div className="cm-drawer absolute inset-y-0 left-0 w-[17rem] max-w-[85vw] shadow-xl">
            <Sidebar onNavigate={() => setAberta(false)} />
            <button
              type="button"
              onClick={() => setAberta(false)}
              className="cm-on-dark absolute right-3 top-5 flex h-9 w-9 items-center justify-center rounded-md text-sidebar-muted hover:bg-sidebar-raised hover:text-sidebar-text"
              autoFocus
            >
              <X className="h-5 w-5" aria-hidden />
              <span className="sr-only">Fechar menu</span>
            </button>
          </div>
        </div>
      )}

      <div className="lg:pl-[15rem]">
        {sangria ? (
          <main>{children}</main>
        ) : (
          <main className="mx-auto max-w-5xl px-4 py-7 sm:px-8 lg:px-12 lg:py-10">{children}</main>
        )}
      </div>
    </div>
  );
}

/**
 * O cabeçalho que a landing sempre teve, no tema escuro anterior.
 *
 * A landing fica fora deste redesign (ela é refeita depois, com clipes reais).
 * `.theme-legacy` devolve os tokens antigos só aqui dentro.
 */
function LegacyMarketingChrome({ children }: { children: React.ReactNode }) {
  return (
    <div className="theme-legacy min-h-screen text-body antialiased">
      <header className="border-b border-line px-4 py-4 sm:px-6">
        <div className="mx-auto flex max-w-4xl items-center gap-3">
          <Link href="/" className="text-title font-semibold text-mint">
            ClipMint
          </Link>
          <span className="hidden text-label text-ink-muted sm:inline">
            cortes verticais a partir de vídeos longos
          </span>
          <Link
            href="/como-funciona"
            className="text-label text-ink-dim transition-colors hover:text-ink"
          >
            Como usar
          </Link>
          <div className="ml-auto flex items-center gap-2">
            <Link
              href="/login"
              className="rounded-sm bg-mint-strong px-3 py-1.5 text-label font-medium text-base transition-colors hover:bg-mint"
            >
              Criar conta
            </Link>
          </div>
        </div>
      </header>
      <main className="mx-auto max-w-4xl px-4 py-6 sm:px-6 sm:py-8">{children}</main>
    </div>
  );
}
