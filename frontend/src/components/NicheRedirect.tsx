"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";

import { listProfiles } from "@/lib/api";
import type { SourceType } from "@/lib/types";

/**
 * As rotas antigas de conta (`/podcast`, `/gameplay`, `/siege`), preservadas.
 *
 * Elas eram a entrada de uma "conta" quando conta era um enum. A reorganização
 * as substituiu por `/perfis/<id>`, mas link salvo e aba aberta não podem
 * quebrar — então aqui a rota encontra o perfil daquela rubrica e leva para ele.
 *
 * Quando não existe perfil daquele tipo, não inventa um: oferece criar, com a
 * rubrica já escolhida.
 */
export default function NicheRedirect({ source }: { source: SourceType }) {
  const router = useRouter();
  const [semPerfil, setSemPerfil] = useState(false);

  useEffect(() => {
    listProfiles()
      .then((perfis) => {
        const alvo = perfis.find((p) => p.source_type === source);
        if (alvo) router.replace(`/perfis/${alvo.id}`);
        else setSemPerfil(true);
      })
      .catch(() => setSemPerfil(true));
  }, [source, router]);

  if (!semPerfil) {
    return <p className="py-20 text-center text-ink-dim">Abrindo o perfil...</p>;
  }

  return (
    <div className="rounded-md border border-line bg-raised px-6 py-12 text-center">
      <p className="text-title font-medium text-ink">
        Você ainda não tem um perfil desta rubrica
      </p>
      <p className="mt-1 text-body text-ink-dim">
        As contas viraram perfis, que você cria e configura como quiser.
      </p>
      <div className="mt-5 flex flex-col justify-center gap-2 sm:flex-row">
        <Link
          href="/perfis/novo"
          className="rounded-sm bg-mint-strong px-5 py-2.5 text-body font-medium text-base transition-colors hover:bg-mint"
        >
          Criar perfil
        </Link>
        <Link
          href="/"
          className="rounded-sm border border-line px-5 py-2.5 text-body text-ink-dim transition-colors hover:border-line-strong hover:text-ink"
        >
          Meus perfis
        </Link>
      </div>
    </div>
  );
}
