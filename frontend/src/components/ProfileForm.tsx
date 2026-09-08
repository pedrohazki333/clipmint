"use client";

import { useRouter, useSearchParams } from "next/navigation";
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
import ClipPreview from "@/components/ClipPreview";
import { Button, ErroFaixa, Field, Input } from "@/components/ui";
import { getClipWatermarkUrl } from "@/lib/api";
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
  const params = useSearchParams();
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

    // Continuação da jornada que começou no hero da landing: se a pessoa
    // chegou aqui com uma URL no bolso, o perfil recém-criado já abre na tela
    // de gerar, com o link preenchido. Sem `url`, nada muda — é o caminho de
    // sempre, para a página do perfil.
    const url = editando ? null : params.get("url");
    router.replace(
      url
        ? `/perfis/${salvoId}/gerar?url=${encodeURIComponent(url)}`
        : `/perfis/${salvoId}`,
    );
    router.refresh();
  }

  /**
   * Criar pede DUAS coisas. Editar mostra tudo.
   *
   * O formulário tinha 14 campos na criação, e 12 deles têm padrão razoável —
   * ícone, layout, legenda, duas logos e sete campos de cor, fonte e @. Pedir
   * essas doze decisões antes do primeiro clipe é pedir que a pessoa escolha
   * sem ter visto o que a escolha muda.
   *
   * Nome e rubrica ficam porque não têm padrão: um perfil sem nome não se
   * distingue do próximo, e a rubrica decide como o vídeo é analisado.
   */
  const soOEssencial = !editando;

  return (
    <div className="flex flex-col gap-6">
      <div>
        <Link
          href={editando ? `/perfis/${profile!.id}` : "/dashboard"}
          className="text-label text-ink-dim transition-colors hover:text-ink"
        >
          ← {editando ? profile!.name : "Meus perfis"}
        </Link>
        <h1 className="mt-2 text-display font-semibold text-ink">
          {editando ? "Editar perfil" : "Criar perfil"}
        </h1>
        <p className="mt-1 text-body text-ink-dim">
          {editando
            ? "A identidade e o padrão de geração deste perfil."
            : "Duas respostas e você já pode gerar. O resto se ajusta depois."}
        </p>
      </div>

      <form onSubmit={handleSubmit} className="flex flex-col gap-6">
        <div className="flex flex-col gap-6 rounded-md border border-line bg-raised p-4 sm:p-6">
          <Field
            label="Nome do perfil"
            htmlFor="nome"
            hint="Só para você se achar: um perfil por canal, ou por linha editorial. Aparece na sua lista, nunca no clipe."
          >
            <Input
              id="nome"
              value={name}
              onChange={(e) => setName(e.target.value)}
              maxLength={60}
              autoFocus
              placeholder="Ex.: Meus cortes"
            />
          </Field>

          <Field
            label="Rubrica de análise"
            htmlFor="nicho"
            hint="É o critério que dá nota a cada trecho do vídeo. Podcast pontua gancho verbal, arco de resolução e frase-momento; Gameplay pontua pico visual, reviravolta e legibilidade sem som. Escolha pelo tipo de vídeo que você vai enviar."
          >
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
              <p className="text-label text-ink-dim">{nicho.description}</p>
            )}
          </Field>

          {!soOEssencial && (
            <Field
              label="Ícone"
              hint="Só para diferenciar os perfis na lista."
            >
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
            </Field>
          )}
        </div>

        {/* ── Aparência: só na edição, e sempre ao lado do preview ──────────
            Estes controles não fazem sentido sem ver o que mudam. Enquanto
            moravam numa coluna de painéis soltos, escolher uma cor de banner
            era escolher no escuro — o resultado só aparecia depois de gastar
            crédito num vídeo. */}
        {!soOEssencial && (
          <div className="grid grid-cols-[minmax(0,1fr)] gap-6 lg:grid-cols-[minmax(0,1fr)_18rem] lg:items-start">
            {/* ── Prévia ───────────────────────────────────────────────────
                Primeira no DOM e grudada no topo: no celular ela é uma tira
                fina que acompanha a rolagem, porque uma prévia que só aparece
                depois de todos os controles não serve para nada — a pessoa
                mexe na cor aqui e o resultado está três telas abaixo.
                No desktop ela vira a coluna da direita, em tamanho cheio. */}
            <div className="sticky top-0 z-20 -mx-4 min-w-0 border-b border-line bg-base px-4 py-3 sm:-mx-6 sm:px-6 lg:order-2 lg:top-6 lg:mx-0 lg:border-0 lg:bg-transparent lg:px-0 lg:py-0">
              <div className="flex items-center gap-4 lg:block">
                <div className="w-[88px] flex-shrink-0 lg:w-full">
                  <ClipPreview
                    layout={layout}
                    subtitle={subtitle}
                    brand={brand}
                    watermarkUrl={
                      profile?.id
                        ? getClipWatermarkUrl({ source: sourceType, profileId: profile.id })
                        : undefined
                    }
                  />
                </div>
                <div className="min-w-0 lg:mt-3">
                  <p className="text-label uppercase tracking-[0.16em] text-ink-dim">
                    Prévia
                  </p>
                  {/* No celular a tira tem que caber numa linha de leitura;
                      o porquê completo fica onde há espaço para ele. */}
                  <p className="mt-1 text-label leading-relaxed text-ink-dim">
                    Atualiza enquanto você mexe.
                    <span className="hidden lg:inline">
                      {" "}
                      Proporções, posição e cor são as do arquivo final. A
                      quebra de linha do título é aproximada — quem quebra de
                      verdade é o servidor, com a fonte instalada nele.
                    </span>
                  </p>
                </div>
              </div>
            </div>

            <div className="flex min-w-0 flex-col gap-6 rounded-md border border-line bg-raised p-4 sm:p-6 lg:order-1">
              <div>
                <p className="text-body font-medium text-ink">Padrão de geração</p>
                <p className="mt-1 text-label text-ink-dim">
                  Como o formulário de geração vem preenchido. Dá para mudar em
                  cada vídeo.
                </p>
              </div>
              <LayoutModeSelector
                value={layout}
                onChange={setLayout}
                source={sourceType}
              />
              <SubtitleModeSelector value={subtitle} onChange={setSubtitle} />

              {editando && brandBase === null ? (
                <p className="border-t border-line pt-6 text-body text-ink-dim">
                  Carregando a marca deste perfil...
                </p>
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
            </div>
          </div>
        )}

        {erro && <ErroFaixa>{erro}</ErroFaixa>}

        <div className="flex flex-col gap-2 sm:flex-row sm:justify-end">
          <Link
            href={editando ? `/perfis/${profile!.id}` : "/dashboard"}
            className="rounded-sm border border-line px-5 py-2.5 text-center text-body text-ink-dim transition-colors hover:border-line-strong hover:text-ink"
          >
            Cancelar
          </Link>
          <Button type="submit" disabled={salvando || !name.trim() || !marcaValida}>
            {salvando
              ? "Salvando..."
              : editando
              ? "Salvar alterações"
              : "Criar perfil"}
          </Button>
        </div>

        {soOEssencial && (
          <p className="text-label text-ink-dim">
            Cores, fonte, logo e formato do corte ficam em Editar perfil, com a
            prévia do clipe ao lado.
          </p>
        )}
      </form>
    </div>
  );
}
