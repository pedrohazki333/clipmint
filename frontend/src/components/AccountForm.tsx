"use client";

import { useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";

import { getApiErrorMessage } from "@/lib/api";
import axios from "axios";

type Modo = "entrar" | "criar";

/**
 * Entrada por conta — só do build público.
 *
 * Fala direto com o backend (`/api/auth/*`), que é quem emite o cookie de
 * sessão. O middleware do Next não participa da decisão: ele só verifica se
 * existe cookie, para evitar uma ida inútil ao servidor.
 */
export default function AccountForm() {
  const router = useRouter();
  const params = useSearchParams();
  const [modo, setModo] = useState<Modo>("entrar");
  const [email, setEmail] = useState("");
  const [senha, setSenha] = useState("");
  const [erro, setErro] = useState("");
  const [enviando, setEnviando] = useState(false);

  const criando = modo === "criar";

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setEnviando(true);
    setErro("");
    try {
      await axios.post(criando ? "/api/auth/register" : "/api/auth/login", {
        email: email.trim(),
        password: senha,
      });
      // replace() para a tela de login não ficar no histórico do navegador
      router.replace(params.get("next") || "/");
      router.refresh();
    } catch (err) {
      setErro(
        getApiErrorMessage(
          err,
          criando ? "Não foi possível criar a conta." : "Não foi possível entrar.",
        ),
      );
    } finally {
      setEnviando(false);
    }
  }

  return (
    <form onSubmit={handleSubmit} className="mx-auto mt-16 max-w-sm space-y-4">
      <div>
        <h1 className="text-title font-bold text-ink">
          {criando ? "Criar conta" : "Entrar no ClipMint"}
        </h1>
        <p className="mt-1 text-body text-ink-dim">
          {criando
            ? "Seus vídeos e clipes ficam só na sua conta."
            : "Use o e-mail e a senha da sua conta."}
        </p>
      </div>

      <input
        type="email"
        value={email}
        onChange={(e) => setEmail(e.target.value)}
        autoFocus
        autoComplete="email"
        placeholder="seu@email.com"
        className="w-full rounded-sm border border-line bg-raised px-4 py-2.5 text-ink placeholder-ink-muted outline-none focus:border-mint"
      />

      <div>
        <input
          type="password"
          value={senha}
          onChange={(e) => setSenha(e.target.value)}
          autoComplete={criando ? "new-password" : "current-password"}
          placeholder="Senha"
          className="w-full rounded-sm border border-line bg-raised px-4 py-2.5 text-ink placeholder-ink-muted outline-none focus:border-mint"
        />
        {criando && (
          <p className="mt-1.5 text-label text-ink-muted">
            Pelo menos 12 caracteres. Uma frase que você lembre vale mais que
            símbolos.
          </p>
        )}
      </div>

      {erro && <p className="text-body text-danger">{erro}</p>}

      <button
        type="submit"
        disabled={enviando || !email || !senha}
        className="w-full rounded-sm bg-mint-strong px-4 py-2.5 font-medium text-white transition hover:bg-mint disabled:cursor-not-allowed disabled:opacity-50"
      >
        {enviando
          ? criando
            ? "Criando..."
            : "Entrando..."
          : criando
          ? "Criar conta"
          : "Entrar"}
      </button>

      <button
        type="button"
        onClick={() => {
          setModo(criando ? "entrar" : "criar");
          setErro("");
        }}
        className="w-full text-body text-ink-dim transition hover:text-ink"
      >
        {criando ? "Já tenho conta" : "Criar uma conta"}
      </button>
    </form>
  );
}
