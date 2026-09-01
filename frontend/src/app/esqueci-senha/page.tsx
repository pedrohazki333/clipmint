"use client";

import { useState } from "react";
import Link from "next/link";

import { forgotPassword, getApiErrorMessage } from "@/lib/api";

export default function EsqueciSenhaPage() {
  const [email, setEmail] = useState("");
  const [enviado, setEnviado] = useState(false);
  const [erro, setErro] = useState("");
  const [enviando, setEnviando] = useState(false);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setEnviando(true);
    setErro("");
    try {
      await forgotPassword(email.trim());
      setEnviado(true);
    } catch (err) {
      setErro(getApiErrorMessage(err, "Não foi possível pedir a redefinição."));
    } finally {
      setEnviando(false);
    }
  }

  if (enviado) {
    return (
      <div className="mx-auto mt-16 max-w-sm space-y-4">
        <h1 className="text-title font-bold text-ink">Confira seu e-mail</h1>
        {/*
          A mensagem não afirma que a conta existe. O servidor responde igual
          nos dois casos para não entregar quem tem conta, e a tela precisa
          dizer a mesma verdade — prometer "enviamos" para um e-mail sem conta
          deixaria a pessoa esperando.
        */}
        <p className="text-body text-ink-dim">
          Se existir uma conta com <strong className="text-ink">{email}</strong>, o
          link de redefinição está a caminho. Ele vale por uma hora e só funciona
          uma vez.
        </p>
        <p className="text-body text-ink-dim">
          Não chegou? Confira o spam e o endereço digitado.
        </p>
        <Link href="/login" className="inline-block text-body text-mint hover:underline">
          ← Voltar para entrar
        </Link>
      </div>
    );
  }

  return (
    <form onSubmit={handleSubmit} className="mx-auto mt-16 max-w-sm space-y-4">
      <div>
        <h1 className="text-title font-bold text-ink">Esqueci minha senha</h1>
        <p className="mt-1 text-body text-ink-dim">
          Informe o e-mail da conta e mandamos um link para você criar outra senha.
        </p>
      </div>

      <input
        type="email"
        value={email}
        onChange={(e) => setEmail(e.target.value)}
        autoFocus
        required
        placeholder="seu@email.com"
        className="w-full rounded-sm border border-line bg-raised px-4 py-2.5 text-ink placeholder-ink-muted outline-none focus:border-mint"
      />

      {erro && <p className="text-body text-danger">{erro}</p>}

      <button
        type="submit"
        disabled={enviando || !email.trim()}
        className="w-full rounded-sm bg-mint-strong px-4 py-2.5 text-body font-medium text-base transition-colors hover:bg-mint disabled:opacity-50"
      >
        {enviando ? "Enviando..." : "Enviar link"}
      </button>

      <Link href="/login" className="inline-block text-body text-ink-dim hover:text-ink">
        ← Voltar para entrar
      </Link>
    </form>
  );
}
