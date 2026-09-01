"use client";

import { useRouter } from "next/navigation";
import { useEffect, useRef, useState } from "react";
import Link from "next/link";

import { AVATARS, AVATAR_LABEL, AvatarIcon, avatarKey } from "@/lib/avatars";
import { PUBLIC_NICHES } from "@/lib/features";
import { layoutAllowed, layoutsFor } from "@/lib/layouts";
import { PERSONAL_NICHES } from "@/personal";
import { createProfile, getApiErrorMessage, updateProfile } from "@/lib/api";
import {
  applyBrandDraft,
  brandSujo,
  draftPadrao,
  loadBrandDraft,
  type BrandDraft,
  type BrandSnapshot,
  type FontOption,
} from "@/lib/brand";
import type { LayoutMode, Profile, SubtitleMode } from "@/lib/types";
import BrandSettings from "@/components/BrandSettings";
import { bannerValido } from "@/components/BannerColorSettings";
import { barValida } from "@/components/BarStyleSettings";
import LayoutModeSelector from "@/components/LayoutModeSelector";
import SubtitleModeSelector from "@/components/SubtitleModeSelector";

/**
 * Criar ou editar um perfil.
 *
 * O nicho aqui é a rubrica BASE — a lista é a mesma que o build permite, e um
 * perfil não cria critérios de análise novos. Um perfil chamado "Cortes de
 * Entrevistas" com base Podcast é legítimo; um nicho "Entrevistas" não existe.
 *
 * Layout e legenda são os DEFAULTS do formulário de geração, não travas: a tela
 * de gerar continua deixando mudá-los por job, como sempre deixou.
 *
 * A marca mora AQUI DENTRO, no mesmo card e sob o mesmo botão. Os presets são
 * gravados numa pasta com o id do perfil, que na criação ainda não existe — por
 * isso o submit cria o perfil primeiro e só então aplica o rascunho de marca
 * (ver `lib/brand.ts`). Antes disso a marca só existia na edição, com um botão
 * de salvar por painel.
 */

const NICHES = [...PUBLIC_NICHES, ...PERSONAL_NICHES];

interface Props {
  /** Ausente = criar. Presente = editar. */
  profile?: Profile;
}

export default function ProfileForm({ profile }: Props) {
  const router = useRouter();
  const editando = Boolean(profile);

  const [name, setName] = useState(profile?.name ?? "");
  const [sourceType, setSourceType] = useState(
    profile?.source_type ?? NICHES[0].source,
  );
  const [avatar, setAvatar] = useState(avatarKey(profile?.avatar));
  const [layout, setLayout] = useState<LayoutMode>(
    profile?.default_layout_mode ?? "cover",
  );
  const [subtitle, setSubtitle] = useState<SubtitleMode>(
    profile?.default_subtitle_mode ?? "word_highlight",
  );
  const [erro, setErro] = useState("");
  const [salvando, setSalvando] = useState(false);

  // ── Marca ───────────────────────────────────────────────────────────────────
  const [brand, setBrand] = useState<BrandDraft>(draftPadrao());
  const [brandBase, setBrandBase] = useState<BrandSnapshot | null>(null);
  const [fonts, setFonts] = useState<FontOption[]>([]);
  /** A pessoa já mexeu na marca? Se mexeu, recarregar não pode atropelar. */
  const tocouNaMarca = useRef(false);

  /**
   * Se o perfil já existe, os presets dele estão gravados. Se não, o que se lê
   * é o que valeria para ele — no build público, a marca do próprio ClipMint
   * (ver `preset_path` em backend/app/services/branding.py).
   */
  useEffect(() => {
    let cancelado = false;
    loadBrandDraft({ source: sourceType, profileId: profile?.id }).then((snap) => {
      if (cancelado) return;
      setBrandBase(snap);
      setFonts(snap.fonts);
      if (!tocouNaMarca.current) setBrand(snap.draft);
    });
    return () => {
      cancelado = true;
    };
  }, [sourceType, profile?.id]);

  function mudarMarca(v: BrandDraft) {
    tocouNaMarca.current = true;
    setBrand(v);
  }

  /**
   * O perfil recém-criado, quando a marca falhou depois de ele nascer.
   *
   * Sem isto, tentar de novo criaria um segundo perfil idêntico — o primeiro
   * já está gravado.
   */
  const [criadoId, setCriadoId] = useState<string | null>(null);

  const nicho = NICHES.find((n) => n.source === sourceType);

  /** Trocar o nicho traz o layout que aquele nicho usa — é só sugestão. */
  function handleNiche(valor: string) {
    const escolhido = NICHES.find((n) => n.source === valor);
    if (!escolhido) return;
    setSourceType(escolhido.source);
    // O layout preferido do nicho, se ele o aceitar; senão o primeiro que
    // aceita. Sem isto, trocar podcast→gameplay deixaria "capa" selecionada,
    // que é justamente o que aquela rubrica não tem.
    setLayout(
      layoutAllowed(escolhido.layout, escolhido.source)
        ? escolhido.layout
        : layoutsFor(escolhido.source)[0],
    );
  }

  const marcaValida = bannerValido(brand.banner) && barValida(brand.bar);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setSalvando(true);
    setErro("");
    const payload = {
      name: name.trim(),
      source_type: sourceType,
      avatar,
      default_layout_mode: layout,
      default_subtitle_mode: subtitle,
    };

    // O id que já existe: o do perfil em edição, ou o de um create que deu
    // certo e cuja marca falhou depois.
    const alvo = profile?.id ?? criadoId;
    let salvoId: string;
    try {
      const salvo = alvo
        ? await updateProfile(alvo, payload)
        : await createProfile(payload);
      salvoId = salvo.id;
      if (!profile) setCriadoId(salvo.id);
    } catch (err) {
      setErro(
        getApiErrorMessage(
          err,
          editando
            ? "Não foi possível salvar o perfil."
            : "Não foi possível criar o perfil.",
        ),
      );
      setSalvando(false);
      return;
    }

    // A marca só pode ser gravada depois: a pasta dos presets tem o id dentro.
    if (brandBase && brandSujo(brand, brandBase)) {
      try {
        await applyBrandDraft(
          { source: sourceType, profileId: salvoId },
          brand,
          brandBase,
        );
      } catch (err) {
        setErro(
          getApiErrorMessage(
            err,
            "O perfil foi salvo, mas a marca não. Tente salvar de novo.",
          ),
        );
        setSalvando(false);
        return;
      }
    }

    router.replace(`/perfis/${salvoId}`);
    router.refresh();
  }

  return (
    <div className="flex flex-col gap-6">
      <div>
        <Link
          href={editando ? `/perfis/${profile!.id}` : "/"}
          className="text-label text-ink-dim transition-colors hover:text-ink"
        >
          ← {editando ? profile!.name : "Meus perfis"}
        </Link>
        <h1 className="mt-2 text-display font-semibold text-ink">
          {editando ? "Editar perfil" : "Criar novo perfil"}
        </h1>
        <p className="mt-1 text-body text-ink-dim">
          Configure a identidade e o padrão de geração dos seus clipes.
        </p>
      </div>

      <form
        onSubmit={handleSubmit}
        className="flex flex-col gap-6 rounded-md border border-line bg-raised p-4 sm:p-6"
      >
        <div className="flex flex-col gap-2">
          <label htmlFor="nome" className="text-body font-medium text-ink">
            Nome do perfil
          </label>
          <input
            id="nome"
            value={name}
            onChange={(e) => setName(e.target.value)}
            maxLength={60}
            autoFocus
            placeholder="Ex.: Meus cortes"
            className="w-full rounded-sm border border-line bg-inset px-4 py-2.5 text-body text-ink placeholder-ink-muted outline-none focus:border-mint"
          />
        </div>

        <div className="flex flex-col gap-2">
          <label htmlFor="nicho" className="text-body font-medium text-ink">
            Rubrica de análise
          </label>
          <select
            id="nicho"
            value={sourceType}
            onChange={(e) => handleNiche(e.target.value)}
            className="w-full rounded-sm border border-line bg-inset px-4 py-2.5 text-body text-ink outline-none focus:border-mint"
          >
            {NICHES.map((n) => (
              <option key={n.source} value={n.source}>
                {n.title}
              </option>
            ))}
          </select>
          {nicho && (
            <p className="text-label text-ink-muted">{nicho.description}</p>
          )}
        </div>

        <div className="flex flex-col gap-2">
          <span className="text-body font-medium text-ink">Ícone</span>
          <div className="flex flex-wrap gap-2">
            {AVATARS.map((chave) => (
              <button
                key={chave}
                type="button"
                onClick={() => setAvatar(chave)}
                title={AVATAR_LABEL[chave]}
                aria-pressed={avatar === chave}
                className={`flex h-12 w-12 items-center justify-center rounded-sm border transition-colors ${
                  avatar === chave
                    ? "border-mint bg-mint-soft text-mint"
                    : "border-line bg-inset text-ink-dim hover:border-line-strong hover:text-ink"
                }`}
              >
                <AvatarIcon name={chave} className="h-5 w-5" />
              </button>
            ))}
          </div>
        </div>

        <div className="border-t border-line pt-6">
          <p className="mb-1 text-body font-medium text-ink">
            Padrão de geração
          </p>
          <p className="mb-4 text-label text-ink-muted">
            Como o formulário de geração vem preenchido. Dá para mudar em cada
            vídeo.
          </p>
          <div className="flex flex-col gap-5">
            <LayoutModeSelector
              value={layout}
              onChange={setLayout}
              source={sourceType}
            />
            <SubtitleModeSelector value={subtitle} onChange={setSubtitle} />
          </div>
        </div>

        {/*
          Editando, a marca só existe depois que `loadBrandDraft` volta — e até
          lá `brand` vale o padrão de fábrica. Mostrar os painéis nesse estado
          exibe cores que NÃO são as do perfil como se fossem, e quem abre a
          tela conclui que a configuração se perdeu. Enquanto não chega, o
          honesto é dizer que está carregando.

          Na criação não se aplica: ali o padrão do nicho é mesmo o valor certo
          de partida, e segurar o formulário só atrasaria quem quer preencher.
        */}
        {editando && brandBase === null ? (
          <div className="rounded-md border border-line bg-raised px-6 py-12 text-center">
            <p className="text-body text-ink-dim">
              Carregando a marca deste perfil...
            </p>
          </div>
        ) : (
          <BrandSettings
            source={sourceType}
            profileId={profile?.id}
            draft={brand}
            onChange={mudarMarca}
            fonts={fonts}
            disabled={salvando}
          />
        )}

        {erro && (
          <p className="rounded-sm border border-danger/40 bg-danger-soft px-3 py-2 text-body text-danger">
            {erro}
          </p>
        )}

        <div className="flex flex-col gap-2 sm:flex-row sm:justify-end">
          <Link
            href={editando ? `/perfis/${profile!.id}` : "/"}
            className="rounded-sm border border-line px-5 py-2.5 text-center text-body text-ink-dim transition-colors hover:border-line-strong hover:text-ink"
          >
            Cancelar
          </Link>
          <button
            type="submit"
            disabled={salvando || !name.trim() || !marcaValida}
            className="rounded-sm bg-mint-strong px-5 py-2.5 text-body font-medium text-base transition-colors hover:bg-mint disabled:cursor-not-allowed disabled:opacity-50"
          >
            {salvando
              ? "Salvando..."
              : editando
              ? "Salvar alterações"
              : "Criar perfil"}
          </button>
        </div>
      </form>
    </div>
  );
}
