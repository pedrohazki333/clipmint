"use client";

import Link from "next/link";
import { useEffect, useState } from "react";

import { getApiErrorMessage, getMe, getUsage, listProfiles, logoutAll } from "@/lib/api";
import { IS_PUBLIC_BUILD } from "@/lib/build";
import type { AccountUsage, AccountUser, Profile } from "@/lib/types";
import LogoutButton from "@/components/LogoutButton";

/**
 * A conta de quem está usando.
 *
 * Reúne o que a pessoa precisa saber sobre si: com qual e-mail está logada, o
 * que já gastou da cota da janela (a MESMA contagem que barra um job novo, ver
 * services/quota.py), quantos perfis tem, e como sair — daqui ou de todos os
 * aparelhos.
 *
 * Na versão pessoal não existe conta: a entrada é por senha única. A página
 * continua existindo para a navbar não ter um link quebrado, mas diz isso.
 */
export default function ContaPage() {
  const [user, setUser] = useState<AccountUser | null>(null);
  const [usage, setUsage] = useState<AccountUsage | null>(null);
  const [profiles, setProfiles] = useState<Profile[] | null>(null);
  const [erro, setErro] = useState("");
  const [encerrando, setEncerrando] = useState(false);
  const [encerradas, setEncerradas] = useState<number | null>(null);

  useEffect(() => {
    if (!IS_PUBLIC_BUILD) return;
    getMe()
      .then(setUser)
      .catch((err) =>
        setErro(getApiErrorMessage(err, "Não foi possível carregar a conta.")),
      );
    getUsage().then(setUsage).catch(() => setUsage(null));
    listProfiles().then(setProfiles).catch(() => setProfiles(null));
  }, []);

  async function sairDeTodos() {
    setEncerrando(true);
    setErro("");
    try {
      setEncerradas(await logoutAll());
      // A sessão atual também caiu: o cookie já não vale.
      window.location.href = "/login";
    } catch (err) {
      setErro(getApiErrorMessage(err, "Não foi possível encerrar as sessões."));
      setEncerrando(false);
    }
  }

  if (!IS_PUBLIC_BUILD) {
    return (
      <div className="flex flex-col gap-4">
        <h1 className="text-display font-semibold text-ink">Sua conta</h1>
        <p className="rounded-md border border-line bg-raised p-6 text-body text-ink-dim">
          Esta instalação entra por senha única, sem contas individuais.
        </p>
        <LogoutButton className="self-start rounded-sm border border-line px-5 py-2.5 text-body text-ink-dim transition-colors hover:border-line-strong hover:text-ink" />
      </div>
    );
  }

  const nome = user?.display_name?.trim() || user?.email || "—";
  const inicial = nome.charAt(0).toUpperCase();

  return (
    <div className="flex flex-col gap-6">
      <div>
        <Link
          href="/"
          className="text-label text-ink-dim transition-colors hover:text-ink"
        >
          ← Meus perfis
        </Link>
        <h1 className="mt-2 text-display font-semibold text-ink">Sua conta</h1>
      </div>

      {erro && (
        <p className="rounded-sm border border-danger/40 bg-danger-soft px-3 py-2 text-body text-danger">
          {erro}
        </p>
      )}

      {/* Identidade */}
      <div className="flex items-center gap-4 rounded-md border border-line bg-raised p-4 sm:p-6">
        <span className="flex h-14 w-14 flex-shrink-0 items-center justify-center rounded-full bg-mint-soft text-title font-semibold text-mint">
          {inicial}
        </span>
        <div className="min-w-0">
          <p className="truncate text-title font-semibold text-ink">{nome}</p>
          <p className="truncate text-body text-ink-dim">{user?.email ?? "—"}</p>
          {user?.is_owner && (
            <span className="mt-1 inline-block rounded-sm border border-mint/40 bg-mint-soft px-2 py-0.5 text-label text-mint">
              Administra esta instalação
            </span>
          )}
        </div>
      </div>

      {/* Cota da janela — os mesmos números que barram um job novo */}
      <div className="rounded-md border border-line bg-raised p-4 sm:p-6">
        <h2 className="text-title font-semibold text-ink">
          Uso {usage ? `nas últimas ${usage.window_hours}h` : ""}
        </h2>
        <p className="mt-1 text-label text-ink-muted">
          A janela é deslizante: cada vídeo sai da conta {usage?.window_hours ?? 24}
          h depois de ter entrado.
        </p>

        {usage ? (
          <div className="mt-4 flex flex-col gap-4">
            <Medidor
              rotulo="Vídeos processados"
              usado={usage.videos_used}
              teto={usage.videos_max}
              unidade=""
            />
            <Medidor
              rotulo="Minutos de vídeo"
              usado={usage.minutes_used}
              teto={usage.minutes_max}
              unidade=" min"
            />
            <p className="text-label text-ink-muted">
              {usage.max_source_minutes > 0
                ? `Vídeo mais longo aceito: ${usage.max_source_minutes} minutos. Acima disso o link é recusado antes do download.`
                : "Sem limite de duração por vídeo."}
            </p>
          </div>
        ) : (
          <p className="mt-4 text-body text-ink-dim">Carregando...</p>
        )}
      </div>

      {/* Perfis */}
      <div className="rounded-md border border-line bg-raised p-4 sm:p-6">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <h2 className="text-title font-semibold text-ink">Seus perfis</h2>
            <p className="mt-1 text-label text-ink-muted">
              Cada perfil tem a própria marca e o próprio histórico.
            </p>
          </div>
          <Link
            href="/"
            className="rounded-sm border border-line px-4 py-2 text-body text-ink-dim transition-colors hover:border-line-strong hover:text-ink"
          >
            Ver perfis
          </Link>
        </div>
        <p className="tabular mt-4 text-display font-semibold text-ink">
          {profiles ? profiles.length : "—"}
        </p>
      </div>

      {/* Sessão */}
      <div className="rounded-md border border-line bg-raised p-4 sm:p-6">
        <h2 className="text-title font-semibold text-ink">Sessão</h2>
        <p className="mt-1 text-label text-ink-muted">
          Sair encerra só este aparelho. Sair de todos derruba também os outros
          navegadores em que você entrou.
        </p>
        {encerradas !== null && (
          <p className="mt-3 text-label text-mint">
            {encerradas} sessão{encerradas === 1 ? "" : "s"} encerrada
            {encerradas === 1 ? "" : "s"}.
          </p>
        )}
        <div className="mt-4 flex flex-col gap-2 sm:flex-row">
          <LogoutButton className="rounded-sm border border-line px-5 py-2.5 text-center text-body text-ink-dim transition-colors hover:border-line-strong hover:text-ink disabled:opacity-50" />
          <button
            type="button"
            onClick={sairDeTodos}
            disabled={encerrando}
            className="rounded-sm border border-line px-5 py-2.5 text-center text-body text-ink-dim transition-colors hover:border-danger/40 hover:text-danger disabled:opacity-50"
          >
            {encerrando ? "Encerrando..." : "Sair de todos os aparelhos"}
          </button>
        </div>
      </div>
    </div>
  );
}

/**
 * Uma barra de consumo. Teto 0 = sem teto, e aí não há barra para desenhar —
 * mostrar uma barra vazia sugeriria um limite que não existe.
 */
function Medidor({
  rotulo,
  usado,
  teto,
  unidade,
}: {
  rotulo: string;
  usado: number;
  teto: number;
  unidade: string;
}) {
  const semTeto = teto <= 0;
  const fracao = semTeto ? 0 : Math.min(1, usado / teto);
  const cheio = fracao >= 1;

  return (
    <div>
      <div className="flex items-baseline justify-between gap-3">
        <span className="text-body text-ink">{rotulo}</span>
        <span className="tabular text-body text-ink-dim">
          {usado}
          {unidade}
          {semTeto ? "" : ` de ${teto}${unidade}`}
        </span>
      </div>
      {semTeto ? (
        <p className="mt-1 text-label text-ink-muted">Sem teto nesta instalação.</p>
      ) : (
        <div className="mt-2 h-2 overflow-hidden rounded-full bg-inset">
          <div
            className={`h-full rounded-full transition-all ${
              cheio ? "bg-danger" : "bg-mint"
            }`}
            style={{ width: `${Math.max(2, fracao * 100)}%` }}
          />
        </div>
      )}
    </div>
  );
}
