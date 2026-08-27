"use client";

import { useCallback, useEffect, useState } from "react";

import { getBalance } from "./api";
import type { Balance } from "./types";

/**
 * O saldo, compartilhado entre a navbar e as telas que o mostram.
 *
 * Não há biblioteca de estado aqui de propósito: o que precisa acontecer é
 * "gastei/recarreguei, atualize o número no topo", e um evento de janela
 * resolve isso sem introduzir uma dependência e um provider no layout inteiro.
 * Quem muda o saldo chama `avisarSaldoMudou()`; quem mostra, escuta.
 */
const EVENTO = "clipmint:saldo";

export function avisarSaldoMudou() {
  if (typeof window !== "undefined") {
    window.dispatchEvent(new Event(EVENTO));
  }
}

export function useSaldo() {
  const [saldo, setSaldo] = useState<Balance | null>(null);
  const [carregando, setCarregando] = useState(true);

  const buscar = useCallback(() => {
    getBalance()
      .then(setSaldo)
      .catch(() => {
        // Sem sessão, ou versão pessoal (onde a rota não existe): o saldo
        // simplesmente não aparece. Não é erro que valha interromper a tela.
        setSaldo(null);
      })
      .finally(() => setCarregando(false));
  }, []);

  useEffect(() => {
    buscar();
    window.addEventListener(EVENTO, buscar);
    return () => window.removeEventListener(EVENTO, buscar);
  }, [buscar]);

  return { saldo, carregando, recarregar: buscar };
}

/** "1.234" — separador de milhar, que é o que faz 1200 e 120 se distinguirem. */
export function formatarCreditos(n: number): string {
  return n.toLocaleString("pt-BR");
}

export function formatarBRL(valor: string | number): string {
  const n = typeof valor === "string" ? Number(valor) : valor;
  return n.toLocaleString("pt-BR", { style: "currency", currency: "BRL" });
}
