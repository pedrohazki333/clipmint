"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";

import { AvatarIcon } from "@/lib/avatars";
import { LAYOUT_LABELS } from "@/lib/layouts";
import { PUBLIC_NICHES } from "@/lib/features";
import { PERSONAL_NICHES, SchedulePanel } from "@/personal";
import { deleteProfile, getApiErrorMessage, getProfile, listJobs } from "@/lib/api";
import type { Job, Profile } from "@/lib/types";
import JobCard from "@/components/JobCard";

/**
 * A visão de um perfil.
 *
 * É a antiga página de conta (`NichePage`) partida em duas: aqui ficam a
 * identidade, as configurações e o histórico; a geração ganhou página própria.
 * Foi essa mistura — configurar e gerar no mesmo lugar — que a reorganização
 * veio desfazer.
 *
 * A marca não mora mais aqui: foi para a edição do perfil, junto do resto do
 * que se configura. Esta tela mostra o que está valendo e o que já saiu dela.
 */

const ACTIVE_POLLING_INTERVAL = 5000; // ms — só enquanto houver job em andamento
const TERMINAL = new Set(["done", "error"]);
const NICHES = [...PUBLIC_NICHES, ...PERSONAL_NICHES];

export default function ProfileView({ profileId }: { profileId: string }) {
  const router = useRouter();
  const [profile, setProfile] = useState<Profile | null>(null);
  const [jobs, setJobs] = useState<Job[]>([]);
  const [erro, setErro] = useState("");
  const [ausente, setAusente] = useState(false);
  const [confirmando, setConfirmando] = useState(false);
  const [excluindo, setExcluindo] = useState(false);

  const carregar = useCallback(async () => {
    try {
      const [p, j] = await Promise.all([
        getProfile(profileId),
        listJobs({ profileId }),
      ]);
      setProfile(p);
      setJobs(j);
      setErro("");
    } catch (err) {
      const status = (err as { response?: { status?: number } })?.response?.status;
      if (status === 404) {
        setAusente(true);
        return;
      }
      setErro(getApiErrorMessage(err, "Não foi possível carregar o perfil."));
    }
  }, [profileId]);

  useEffect(() => {
    carregar();
  }, [carregar]);

  const rodando = jobs.some((j) => !TERMINAL.has(j.status));
  useEffect(() => {
    if (!rodando) return;
    const t = setInterval(carregar, ACTIVE_POLLING_INTERVAL);
    return () => clearInterval(t);
  }, [rodando, carregar]);

  async function excluir() {
    if (!confirmando) {
      setConfirmando(true);
      return;
    }
    setExcluindo(true);
    try {
      await deleteProfile(profileId);
      router.replace("/");
      router.refresh();
    } catch (err) {
      setErro(getApiErrorMessage(err, "Não foi possível excluir o perfil."));
      setExcluindo(false);
      setConfirmando(false);
    }
  }

  if (ausente) {
    return (
      <div className="flex flex-col items-start gap-4">
        <div className="rounded-md border border-line bg-raised p-6">
          <p className="text-body text-ink">Este perfil não existe mais.</p>
          <p className="mt-1 text-label text-ink-dim">
            Os vídeos que saíram dele continuam na sua conta.
          </p>
        </div>
        <Link href="/" className="text-body text-mint hover:text-mint-strong">
          ← Meus perfis
        </Link>
      </div>
    );
  }

  if (!profile) {
    return <p className="py-20 text-center text-ink-dim">Carregando...</p>;
  }

  const nicho = NICHES.find((n) => n.source === profile.source_type);
  const prontos = jobs.filter((j) => j.status === "done").length;

  return (
    <div className="flex flex-col gap-6">
      <Link
        href="/"
        className="text-label text-ink-dim transition-colors hover:text-ink"
      >
        ← Meus perfis
      </Link>

      {/* Identidade e a ação principal */}
      <div className="flex flex-col gap-4 rounded-md border border-line bg-raised p-4 sm:flex-row sm:items-center sm:p-6">
        <div className="flex h-14 w-14 flex-shrink-0 items-center justify-center rounded-md border border-line bg-inset text-mint">
          <AvatarIcon name={profile.avatar} className="h-6 w-6" />
        </div>
        <div className="min-w-0 flex-1">
          <h1 className="truncate text-display font-semibold text-ink">
            {profile.name}
          </h1>
          <p className="text-body text-ink-dim">{nicho?.title ?? profile.source_type}</p>
        </div>
        <div className="flex flex-col gap-2 sm:flex-row">
          <Link
            href={`/perfis/${profile.id}/editar`}
            className="rounded-sm border border-line px-4 py-2.5 text-center text-body text-ink-dim transition-colors hover:border-line-strong hover:text-ink"
          >
            Editar perfil
          </Link>
          <Link
            href={`/perfis/${profile.id}/gerar`}
            className="rounded-sm bg-mint-strong px-5 py-2.5 text-center text-body font-medium text-base transition-colors hover:bg-mint"
          >
            Gerar clipes
          </Link>
        </div>
      </div>

      {erro && (
        <p className="rounded-sm border border-danger/40 bg-danger-soft px-3 py-2 text-body text-danger">
          {erro}
        </p>
      )}

      {/* Configuração atual — o que a geração deste perfil vai usar */}
      <div className="rounded-md border border-line bg-raised p-4 sm:p-6">
        <h2 className="mb-4 text-title font-semibold text-ink">
          Configuração atual
        </h2>
        <dl className="grid gap-3 sm:grid-cols-3">
          <Info rotulo="Rubrica" valor={nicho?.title ?? profile.source_type} />
          <Info
            rotulo="Layout padrão"
            valor={LAYOUT_LABELS[profile.default_layout_mode].nome}
          />
          <Info
            rotulo="Legendas"
            valor={
              { word_highlight: "Palavra a palavra", traditional: "Blocos", none: "Sem legenda" }[
                profile.default_subtitle_mode
              ]
            }
          />
        </dl>
      </div>

      {/* Resumo — os mesmos números da tela de perfis */}
      <div className="grid gap-3 sm:grid-cols-3">
        <Metrica valor={profile.job_count} rotulo="Vídeos processados" />
        <Metrica valor={profile.clip_count} rotulo="Clipes prontos" />
        <Metrica
          valor={prontos}
          rotulo={`de ${jobs.length} vídeo${jobs.length === 1 ? "" : "s"} concluídos`}
        />
      </div>

      {/* Fila de postagem — só na versão pessoal (grade do dono). */}
      {SchedulePanel && <SchedulePanel source={profile.source_type} />}

      {/* Histórico */}
      <div>
        <div className="mb-4 flex items-center justify-between">
          <h2 className="text-title font-semibold text-ink">Últimas gerações</h2>
          <button
            onClick={carregar}
            className="text-label text-ink-dim transition-colors hover:text-ink"
          >
            Atualizar
          </button>
        </div>

        {jobs.length === 0 ? (
          <div className="rounded-md border border-line bg-raised px-6 py-12 text-center">
            <p className="text-body text-ink-dim">
              Este perfil ainda não gerou nada.
            </p>
            <Link
              href={`/perfis/${profile.id}/gerar`}
              className="mt-4 inline-block rounded-sm bg-mint-strong px-5 py-2.5 text-body font-medium text-base transition-colors hover:bg-mint"
            >
              Gerar os primeiros clipes
            </Link>
          </div>
        ) : (
          <div className="flex flex-col gap-3">
            {jobs.map((job) => (
              <JobCard key={job.id} job={job} onDeleted={carregar} />
            ))}
          </div>
        )}
      </div>

      {/* Excluir — por último, e com confirmação */}
      <div className="rounded-md border border-line bg-raised p-4 sm:p-6">
        <h2 className="text-body font-medium text-ink">Excluir perfil</h2>
        <p className="mt-1 text-label text-ink-dim">
          Os vídeos e clipes gerados por ele continuam na sua conta — some só a
          configuração.
        </p>
        <button
          onClick={excluir}
          disabled={excluindo}
          className={`mt-3 rounded-sm border px-4 py-2 text-body transition-colors disabled:opacity-50 ${
            confirmando
              ? "border-danger/40 bg-danger-soft text-danger"
              : "border-line text-ink-dim hover:border-line-strong hover:text-ink"
          }`}
        >
          {excluindo
            ? "Excluindo..."
            : confirmando
            ? "Confirmar exclusão"
            : "Excluir perfil"}
        </button>
      </div>
    </div>
  );
}

function Info({ rotulo, valor }: { rotulo: string; valor: string }) {
  return (
    <div className="rounded-sm border border-line bg-inset px-3 py-2.5">
      <dt className="text-label text-ink-muted">{rotulo}</dt>
      <dd className="mt-0.5 text-body text-ink">{valor}</dd>
    </div>
  );
}

function Metrica({ valor, rotulo }: { valor: number; rotulo: string }) {
  return (
    <div className="rounded-md border border-line bg-raised px-4 py-4">
      <p className="tabular text-display font-semibold text-ink">{valor}</p>
      <p className="text-label text-ink-dim">{rotulo}</p>
    </div>
  );
}
