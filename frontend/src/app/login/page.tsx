"use client";

import { useState, Suspense } from "react";
import { useRouter, useSearchParams } from "next/navigation";

import AccountForm from "@/components/AccountForm";
import { IS_PUBLIC_BUILD } from "@/lib/build";

/** Senha única compartilhada — a porta da versão pessoal. */
function PasswordForm() {
  const router = useRouter();
  const params = useSearchParams();
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setSubmitting(true);
    setError(null);
    try {
      const res = await fetch("/auth/login", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ password }),
      });
      if (!res.ok) {
        const data = await res.json().catch(() => ({}));
        setError(data.error ?? "Não foi possível entrar");
        return;
      }
      // replace() para a tela de login não ficar no histórico do navegador
      router.replace(params.get("next") || "/");
      router.refresh();
    } catch {
      setError("Servidor fora do ar");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <form onSubmit={handleSubmit} className="mx-auto mt-16 max-w-sm space-y-4">
      <div>
        <h1 className="text-title font-bold text-ink">Acesso restrito</h1>
        <p className="mt-1 text-body text-ink-dim">
          Informe a senha para usar o ClipMint.
        </p>
      </div>

      <input
        type="password"
        value={password}
        onChange={(e) => setPassword(e.target.value)}
        autoFocus
        placeholder="Senha"
        className="w-full rounded-sm border border-line bg-raised px-4 py-2.5 text-ink placeholder-ink-muted outline-none focus:border-mint"
      />

      {error && <p className="text-body text-danger">{error}</p>}

      <button
        type="submit"
        disabled={submitting || !password}
        className="w-full rounded-sm bg-mint-strong px-4 py-2.5 font-medium text-white transition hover:bg-mint disabled:cursor-not-allowed disabled:opacity-50"
      >
        {submitting ? "Entrando..." : "Entrar"}
      </button>
    </form>
  );
}

export default function LoginPage() {
  // As duas versões entram por portas diferentes: o produto público tem contas,
  // a ferramenta pessoal tem uma senha compartilhada. O resto do app não sabe
  // disso — daqui para dentro, existe um usuário nos dois casos.
  // useSearchParams exige Suspense no App Router.
  return (
    <Suspense>{IS_PUBLIC_BUILD ? <AccountForm /> : <PasswordForm />}</Suspense>
  );
}
