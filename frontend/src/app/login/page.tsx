"use client";

import { useState, Suspense } from "react";
import { useRouter, useSearchParams } from "next/navigation";

function LoginForm() {
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
        <h1 className="text-xl font-bold text-gray-100">Acesso restrito</h1>
        <p className="mt-1 text-sm text-gray-500">
          Informe a senha para usar o ClipMint.
        </p>
      </div>

      <input
        type="password"
        value={password}
        onChange={(e) => setPassword(e.target.value)}
        autoFocus
        placeholder="Senha"
        className="w-full rounded-lg border border-gray-800 bg-gray-900 px-4 py-2.5 text-gray-100 placeholder-gray-600 outline-none focus:border-emerald-500"
      />

      {error && <p className="text-sm text-red-400">{error}</p>}

      <button
        type="submit"
        disabled={submitting || !password}
        className="w-full rounded-lg bg-emerald-600 px-4 py-2.5 font-medium text-white transition hover:bg-emerald-500 disabled:cursor-not-allowed disabled:opacity-50"
      >
        {submitting ? "Entrando..." : "Entrar"}
      </button>
    </form>
  );
}

export default function LoginPage() {
  // useSearchParams exige Suspense no App Router
  return (
    <Suspense>
      <LoginForm />
    </Suspense>
  );
}
