"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useState } from "react";
import {
  CirclePlus,
  Coins,
  FolderOpen,
  LogOut,
  ShieldCheck,
  Sparkles,
  UserRound,
  UsersRound,
  type LucideIcon,
} from "lucide-react";

import Logo from "@/components/brand/Logo";
import LogoutButton from "@/components/LogoutButton";
import { getMe } from "@/lib/api";
import { IS_PUBLIC_BUILD } from "@/lib/build";
import { formatarCreditos, useSaldo } from "@/lib/creditos";
import type { AccountUser } from "@/lib/types";
import { PERSONAL_TOOLS } from "@/personal";

interface NavItem {
  href: string;
  label: string;
  icon: LucideIcon;
  /** Rotas que acendem este item além do próprio href. */
  ativoEm: (path: string) => boolean;
}

const comeca = (...prefixos: string[]) => (path: string) =>
  prefixos.some((p) => path === p || path.startsWith(`${p}/`));

/**
 * O menu é o que o app tem, e só isso.
 *
 * Créditos e Conta só existem no build público: a versão pessoal não tem
 * cobrança nem contas, e um item que leva a uma tela vazia é pior que nenhum.
 * As ferramentas pessoais (Melhorar vídeo) entram por `PERSONAL_TOOLS`, que é
 * uma lista vazia no stub do build público — o nome nem chega ao bundle dele.
 */
function itens(isOwner: boolean): NavItem[] {
  const base: NavItem[] = [
    {
      href: "/gerar",
      label: "Gerar clipes",
      icon: CirclePlus,
      ativoEm: (p) => p === "/gerar" || /^\/perfis\/[^/]+\/gerar$/.test(p),
    },
    { href: "/projetos", label: "Projetos", icon: FolderOpen, ativoEm: comeca("/projetos", "/jobs") },
    {
      href: "/perfis",
      label: "Perfis",
      icon: UsersRound,
      ativoEm: (p) => comeca("/perfis", "/podcast", "/gameplay", "/siege")(p) && !p.endsWith("/gerar"),
    },
  ];
  const ferramentas: NavItem[] = PERSONAL_TOOLS.map((t) => ({
    href: t.href,
    label: t.title,
    icon: Sparkles,
    ativoEm: comeca(t.href),
  }));
  const conta: NavItem[] = IS_PUBLIC_BUILD
    ? [
        { href: "/creditos", label: "Créditos", icon: Coins, ativoEm: comeca("/creditos", "/recarga") },
        { href: "/conta", label: "Conta", icon: UserRound, ativoEm: comeca("/conta") },
        ...(isOwner
          ? [{ href: "/admin", label: "Admin", icon: ShieldCheck, ativoEm: comeca("/admin") }]
          : []),
      ]
    : [];
  return [...base, ...ferramentas, ...conta];
}

/** O saldo real, sempre à vista. Sem "plano": o modelo de dados não tem um. */
function Saldo() {
  const pathname = usePathname();
  const { saldo, carregando, recarregar } = useSaldo();

  // Trocar de página é o momento natural de reconferir: um job pode ter
  // terminado e devolvido a reserva enquanto a pessoa navegava.
  useEffect(() => {
    recarregar();
  }, [pathname, recarregar]);

  if (carregando || !saldo) return null;

  return (
    <Link
      href="/recarga"
      className="group block rounded-md border border-sidebar-line px-4 py-3.5 transition-colors duration-150 hover:border-sidebar-muted"
    >
      <span className="flex items-center gap-2 text-label font-medium uppercase tracking-[0.08em] text-sidebar-muted">
        <Coins className="h-3.5 w-3.5" aria-hidden />
        Saldo
      </span>
      <span className="mt-1.5 flex items-baseline gap-1.5">
        <span className="font-display text-[1.5rem] font-bold leading-none text-sidebar-text tabular-nums">
          {formatarCreditos(saldo.saldo)}
        </span>
        <span className="text-body text-sidebar-muted">créditos</span>
      </span>
      <span
        className={`mt-2.5 inline-flex text-label font-semibold ${
          saldo.baixo ? "text-coral" : "text-mint-strong"
        } group-hover:underline`}
      >
        {saldo.baixo ? "Saldo baixo — recarregar" : "Recarregar"}
      </span>
    </Link>
  );
}

/** Quem está logado, com a porta para a conta. Só existe no público. */
function ContaAtual({ user }: { user: AccountUser | null }) {
  const nome = user?.display_name?.trim() || user?.email || "Sua conta";
  return (
    <Link
      href="/conta"
      title={user?.email ?? undefined}
      className="flex items-center gap-3 rounded-md px-2 py-2 transition-colors duration-150 hover:bg-sidebar-raised"
    >
      <span className="flex h-9 w-9 flex-shrink-0 items-center justify-center rounded-full bg-sidebar-raised font-display text-body font-bold text-sidebar-text ring-1 ring-sidebar-line">
        {nome.charAt(0).toUpperCase()}
      </span>
      <span className="min-w-0">
        <span className="block truncate text-body font-medium text-sidebar-text">{nome}</span>
        <span className="block text-label text-sidebar-muted">Ver conta</span>
      </span>
    </Link>
  );
}

export default function Sidebar({ onNavigate }: { onNavigate?: () => void }) {
  const pathname = usePathname() ?? "";
  const [user, setUser] = useState<AccountUser | null>(null);

  useEffect(() => {
    if (!IS_PUBLIC_BUILD) return;
    getMe()
      .then(setUser)
      .catch(() => {
        /* sem sessão ou backend fora: a conta aparece com o rótulo neutro */
      });
  }, []);

  return (
    <nav
      aria-label="Principal"
      className="cm-on-dark flex h-full flex-col bg-sidebar px-4 pb-5 pt-7 text-sidebar-text"
    >
      <Link href="/gerar" onClick={onNavigate} className="px-3" aria-label="ClipMint — gerar clipes">
        <Logo tone="dark" size="lg" />
      </Link>

      <div className="mx-3 mt-7 border-t border-sidebar-line" />

      <ul className="mt-6 flex flex-col gap-2">
        {itens(!!user?.is_owner).map((item) => {
          const ativo = item.ativoEm(pathname);
          const Icone = item.icon;
          return (
            <li key={item.href}>
              <Link
                href={item.href}
                onClick={onNavigate}
                aria-current={ativo ? "page" : undefined}
                className={`flex items-center gap-4 rounded-[10px] px-4 py-3.5 text-[1rem] transition-colors duration-150 ${
                  ativo
                    ? "bg-mint-strong font-semibold text-ink"
                    : "text-sidebar-text/90 hover:bg-sidebar-raised hover:text-sidebar-text"
                }`}
              >
                <Icone className="h-5 w-5 flex-shrink-0" strokeWidth={ativo ? 2.25 : 1.75} aria-hidden />
                {item.label}
              </Link>
            </li>
          );
        })}
      </ul>

      <div className="mt-auto flex flex-col gap-4 pt-8">
        {IS_PUBLIC_BUILD ? (
          <>
            <Saldo />
            <div className="border-t border-sidebar-line pt-4">
              <ContaAtual user={user} />
            </div>
          </>
        ) : (
          <div className="border-t border-sidebar-line pt-4">
            <LogoutButton className="flex w-full items-center gap-3 rounded-md px-3.5 py-2.5 text-body text-sidebar-muted transition-colors duration-150 hover:bg-sidebar-raised hover:text-sidebar-text disabled:opacity-50">
              <LogOut className="h-4 w-4" aria-hidden />
              Sair
            </LogoutButton>
          </div>
        )}
      </div>
    </nav>
  );
}
