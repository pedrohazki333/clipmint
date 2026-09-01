"use client";

import { Suspense, useState } from "react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";

import { getApiErrorMessage, resetPassword } from "@/lib/api";

function Formulario() {
  const router = useRouter();
  const params = useSearchParams();
  const token = params.get("token") ?? "";

  const [senha, setSenha] = useState("");
  const [erro, setErro] = useState("");
  const [salvando, setSalvando] = useState(false);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setSalvando(true);
    setErro("");
    try {
      await resetPassword(token, senha);
      // O backend já abriu a sessão e mandou o cookie: a pessoa entra direto.
      // Pedir para logar de novo, logo depois de provar que é dona do e-mail,
      // seria burocracia sem ganho de segurança.
      router.replace("/");
      router.refresh();
    } catch (err) {
      setErro(getApiErrorMessage(err, "Não foi possível trocar a senha."));
      setSalvando(false);
    }
  }

  if (!token) {
    return (
      <div className="mx-auto mt-16 max-w-sm space-y-4">
        <h1 className="text-title font-bold text-ink">Link incompleto</h1>
        <p className="text-body text-ink-dim">
          Este endereço não traz o código de redefinição. Abra o link direto do
          e-mail, sem copiar pela metade.
        </p>
        <Link href="/esqueci-senha" className="inline-block text-body text-mint hover:underline">
          Pedir outro link
        </Link>
      </div>
    );
  }

  return (
    <form onSubmit={handleSubmit} className="mx-auto mt-16 max-w-sm space-y-4">
      <div>
        <h1 className="text-title font-bold text-ink">Criar nova senha</h1>
        <p className="mt-1 text-body text-ink-dim">
          Uma frase que você lembre vale mais que símbolos embaralhados.
        </p>
      </div>

      <input
        type="password"
        value={senha}
        onChange={(e) => setSenha(e.target.value)}
        autoFocus
        required
        placeholder="Nova senha"
        className="w-full rounded-sm border border-line bg-raised px-4 py-2.5 text-ink placeholder-ink-muted outline-none focus:border-mint"
      />

      {erro && <p className="text-body text-danger">{erro}</p>}

      <p className="text-label text-ink-muted">
        Ao trocar a senha, as sessões abertas em outros aparelhos são encerradas.
      </p>

      <button
        type="submit"
        disabled={salvando || !senha}
        className="w-full rounded-sm bg-mint-strong px-4 py-2.5 text-body font-medium text-base transition-colors hover:bg-mint disabled:opacity-50"
      >
        {salvando ? "Trocando..." : "Trocar senha e entrar"}
      </button>
    </form>
  );
}

export default function RedefinirSenhaPage() {
  // useSearchParams exige Suspense no App Router.
  return (
    <Suspense fallback={<p className="py-20 text-center text-ink-dim">Carregando...</p>}>
      <Formulario />
    </Suspense>
  );
}
