"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";

import { IS_PUBLIC_BUILD } from "@/lib/build";

/**
 * Sair — de qualquer uma das duas portas.
 *
 * Público: encerra a sessão no backend (a linha some da tabela `sessions`, e o
 * cookie deixa de valer na hora). Pessoal: limpa o cookie da senha única no
 * próprio Next.
 *
 * O "Saindo..." solta antes de navegar. Ele existia para evitar clique duplo,
 * mas quando a chamada demorava ou falhava o botão ficava preso nesse texto —
 * e o `finally` que navegava não devolvia o estado.
 */
export default function LogoutButton({
  className = "",
  children,
}: {
  className?: string;
  children?: React.ReactNode;
}) {
  const router = useRouter();
  const [saindo, setSaindo] = useState(false);

  async function sair() {
    setSaindo(true);
    try {
      await fetch(IS_PUBLIC_BUILD ? "/api/auth/logout" : "/auth/logout", {
        method: "POST",
      });
    } finally {
      setSaindo(false);
      // Mesmo se a chamada falhar, mandar para o login é o certo: continuar
      // mostrando a interface de quem pediu para sair é pior.
      router.replace("/login");
      router.refresh();
    }
  }

  return (
    <button
      type="button"
      onClick={sair}
      disabled={saindo}
      className={
        className ||
        "ml-auto text-body text-ink-dim transition hover:text-ink disabled:opacity-50"
      }
    >
      {children ?? (saindo ? "Saindo..." : "Sair")}
    </button>
  );
}
