"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";

import { AvatarIcon } from "@/lib/avatars";
import { PUBLIC_NICHES } from "@/lib/features";
import { PERSONAL_NICHES } from "@/personal";
import {
  createJob,
  estimateJob,
  getApiErrorMessage,
  getProfile,
} from "@/lib/api";
import { IS_PUBLIC_BUILD } from "@/lib/build";
import { avisarSaldoMudou } from "@/lib/creditos";
import type {
  ClipMode,
  Estimate,
  LayoutMode,
  ManualMode,
  Profile,
  SourceType,
  SubtitleMode,
} from "@/lib/types";
import CreditConfirm from "@/components/CreditConfirm";
import LowBalanceBanner from "@/components/LowBalanceBanner";
import UrlInput from "@/components/UrlInput";

/**
 * Gerar clipes a partir de um perfil.
 *
 * Mesma chamada de sempre: `POST /api/jobs`, mesmo payload, mesmo pipeline. O
 * perfil só decide o que vem preenchido — e vai junto no `profile_id`, para o
 * job aparecer no histórico dele.
 *
 * O formulário é o `UrlInput` de sempre, sem um campo a mais: quantidade de
 * clipes, duração e idioma não existem por job neste sistema, e inventá-los
 * aqui seria criar funcionalidade em vez de reorganizar.
 */

const NICHES = [...PUBLIC_NICHES, ...PERSONAL_NICHES];

export default function ProfileGenerate({ profileId }: { profileId: string }) {
  const router = useRouter();
  const [profile, setProfile] = useState<Profile | null>(null);
  const [ausente, setAusente] = useState(false);
  const [enviando, setEnviando] = useState(false);
  const [erro, setErro] = useState("");

  // O pedido fica em espera enquanto a pessoa confirma o custo. Guardar o
  // payload inteiro (e não só a URL) é o que permite confirmar sem remontar o
  // formulário — o que ela aprovou é exatamente o que vai ser enviado.
  const [pendente, setPendente] = useState<Parameters<typeof enviar>[0] | null>(
    null,
  );
  const [estimativa, setEstimativa] = useState<Estimate | null>(null);
  const [medindo, setMedindo] = useState(false);
  const [erroEstimativa, setErroEstimativa] = useState("");

  const carregar = useCallback(async () => {
    try {
      setProfile(await getProfile(profileId));
    } catch (err) {
      const status = (err as { response?: { status?: number } })?.response?.status;
      if (status === 404) setAusente(true);
      else setErro(getApiErrorMessage(err, "Não foi possível carregar o perfil."));
    }
  }, [profileId]);

  useEffect(() => {
    carregar();
  }, [carregar]);

  /** O envio de verdade. Só roda depois de a pessoa aprovar o custo. */
  async function enviar(payload: {
    url: string;
    subtitleMode: SubtitleMode;
    layoutMode: LayoutMode;
    clipMode: ClipMode;
    manualClips: string;
    manualMode: ManualMode;
  }) {
    setEnviando(true);
    setErro("");
    try {
      const job = await createJob({
        profile_id: profileId,
        youtube_url: payload.url,
        subtitle_mode: payload.subtitleMode,
        layout_mode: payload.layoutMode,
        // O nicho vem do perfil, não de um seletor: é isso que impede gerar
        // conteúdo de um perfil com a identidade de outro.
        source_type: profile?.source_type,
        clip_mode: payload.clipMode,
        manual_clips: payload.manualClips.trim() || undefined,
        manual_mode: payload.manualMode,
      });
      // A reserva já saiu do saldo: o número no topo precisa acompanhar.
      avisarSaldoMudou();
      router.push(`/jobs/${job.id}`);
    } catch (err) {
      setPendente(null);
      setErro(getApiErrorMessage(err, "Não foi possível iniciar a geração."));
    } finally {
      setEnviando(false);
    }
  }

  async function handleSubmit(
    url: string,
    subtitleMode: SubtitleMode,
    layoutMode: LayoutMode,
    _sourceType: SourceType,
    clipMode: ClipMode,
    manualClips: string,
    manualMode: ManualMode,
  ) {
    const payload = {
      url,
      subtitleMode,
      layoutMode,
      clipMode,
      manualClips,
      manualMode,
    };

    // Versão pessoal: não há crédito, não há o que confirmar. Perguntar ali
    // seria uma caixa de diálogo sobre um custo que não existe.
    if (!IS_PUBLIC_BUILD) {
      await enviar(payload);
      return;
    }

    setPendente(payload);
    setEstimativa(null);
    setErroEstimativa("");
    setErro("");
    setMedindo(true);
    try {
      setEstimativa(await estimateJob(url));
    } catch (err) {
      // O 422 daqui é o MESMO que a criação daria (live, vídeo acima do teto).
      // Mostrar no diálogo é o que faz a pessoa descobrir antes, e não depois
      // de esperar o botão.
      setErroEstimativa(
        getApiErrorMessage(err, "Não foi possível medir este vídeo."),
      );
    } finally {
      setMedindo(false);
    }
  }

  if (ausente) {
    return (
      <div className="flex flex-col items-start gap-4">
        <p className="rounded-md border border-line bg-raised p-6 text-body text-ink">
          Este perfil não existe mais.
        </p>
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

  return (
    <div className="flex flex-col gap-6">
      <div>
        <Link
          href={`/perfis/${profile.id}`}
          className="text-label text-ink-dim transition-colors hover:text-ink"
        >
          ← {profile.name}
        </Link>
        <h1 className="mt-2 text-display font-semibold text-ink">Gerar clipes</h1>
        <p className="mt-1 text-body text-ink-dim">
          Transforme um vídeo longo em clipes verticais prontos para publicar.
        </p>
      </div>

      {/* Com qual identidade — some a dúvida de "para qual conta isso vai" */}
      <div className="flex items-center gap-3 rounded-md border border-line bg-raised px-4 py-3">
        <div className="flex h-10 w-10 flex-shrink-0 items-center justify-center rounded-sm border border-line bg-inset text-mint">
          <AvatarIcon name={profile.avatar} className="h-5 w-5" />
        </div>
        <div className="min-w-0">
          <p className="truncate text-body font-medium text-ink">{profile.name}</p>
          <p className="text-label text-ink-dim">
            {nicho?.title ?? profile.source_type}
          </p>
        </div>
        <Link
          href={`/perfis/${profile.id}/editar`}
          className="ml-auto flex-shrink-0 text-label text-ink-dim transition-colors hover:text-ink"
        >
          Editar
        </Link>
      </div>

      {IS_PUBLIC_BUILD && <LowBalanceBanner />}

      <div className="rounded-md border border-line bg-raised p-4 sm:p-6">
        <UrlInput
          onSubmit={handleSubmit}
          isLoading={enviando}
          lockedSource={profile.source_type}
          defaultLayout={profile.default_layout_mode}
          defaultSubtitle={profile.default_subtitle_mode}
        />
        {erro && (
          <p className="mt-3 rounded-sm border border-danger/40 bg-danger-soft px-3 py-2 text-body text-danger">
            {erro}
          </p>
        )}
      </div>

      {pendente && (
        <CreditConfirm
          estimativa={estimativa}
          carregando={medindo}
          erro={erroEstimativa}
          enviando={enviando}
          onCancel={() => setPendente(null)}
          onConfirm={() => enviar(pendente)}
        />
      )}
    </div>
  );
}
