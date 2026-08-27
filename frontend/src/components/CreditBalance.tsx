"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect } from "react";

import { formatarCreditos, useSaldo } from "@/lib/creditos";

/**
 * O saldo na navbar, sempre à vista.
 *
 * "Sempre" é o requisito: num produto pago por consumo, a pergunta "quanto me
 * resta?" aparece antes de cada ação, e obrigar a pessoa a abrir outra tela
 * para responder é o que faz ela parar de gerar.
 *
 * Baixo fica âmbar e continua clicável para a recarga — o mesmo alvo, sem um
 * segundo botão competindo pela atenção.
 */
export default function CreditBalance() {
  const pathname = usePathname();
  const { saldo, carregando, recarregar } = useSaldo();

  // Trocar de página é o momento natural de reconferir: o saldo pode ter mudado
  // por um job que terminou enquanto a pessoa navegava.
  useEffect(() => {
    recarregar();
  }, [pathname, recarregar]);

  if (carregando || !saldo) return null;

  const baixo = saldo.baixo;

  return (
    <Link
      href="/recarga"
      title={
        baixo
          ? `Saldo baixo: ${formatarCreditos(saldo.saldo)} créditos. Toque para recarregar.`
          : `${formatarCreditos(saldo.saldo)} créditos — 1 crédito = 1 minuto de vídeo`
      }
      className={`flex items-center gap-1.5 rounded-sm border px-2.5 py-1.5 transition-colors ${
        baixo
          ? "border-running bg-running-soft text-running hover:border-running"
          : "border-line bg-inset text-ink-dim hover:border-line-strong hover:text-ink"
      }`}
    >
      <span aria-hidden className="text-label">
        {baixo ? "!" : "◆"}
      </span>
      <span className="tabular text-body font-medium">
        {formatarCreditos(saldo.saldo)}
      </span>
      <span className="hidden text-label sm:inline">créditos</span>
    </Link>
  );
}
