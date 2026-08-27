"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useState } from "react";

import { getMe } from "@/lib/api";
import type { AccountUser } from "@/lib/types";

/**
 * O botão de conta da navbar.
 *
 * Leva para `/conta`, que é onde ficam os dados, o consumo da cota e o sair.
 * Antes a navbar tinha só um "Sair" solto: não havia como ver com qual conta se
 * estava logado, o que num build multiusuário é a primeira pergunta.
 *
 * Só do build público — a versão pessoal não tem contas (ver LogoutButton).
 */
export default function UserMenu() {
  const pathname = usePathname();
  const [user, setUser] = useState<AccountUser | null>(null);

  useEffect(() => {
    getMe()
      .then(setUser)
      .catch(() => {
        /* sem sessão ou backend fora: o botão fica com o rótulo neutro */
      });
  }, [pathname]);

  const nome = user?.display_name?.trim() || user?.email || "Conta";
  const inicial = nome.charAt(0).toUpperCase();
  const ativo = pathname === "/conta";

  return (
    <Link
      href="/conta"
      title={user?.email ?? "Sua conta"}
      aria-current={ativo ? "page" : undefined}
      className={`flex items-center gap-2 rounded-sm border px-2.5 py-1.5 transition-colors ${
        ativo
          ? "border-mint bg-mint-soft text-mint"
          : "border-line bg-inset text-ink-dim hover:border-line-strong hover:text-ink"
      }`}
    >
      <span
        className={`flex h-6 w-6 flex-shrink-0 items-center justify-center rounded-full text-label font-semibold ${
          ativo ? "bg-mint text-base" : "bg-mint-soft text-mint"
        }`}
      >
        {inicial}
      </span>
      <span className="hidden max-w-[14rem] truncate text-body sm:inline">
        {nome}
      </span>
    </Link>
  );
}
