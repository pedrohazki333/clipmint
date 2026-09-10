"use client";

import { useRouter, useSearchParams } from "next/navigation";
import { useEffect, useId, useRef, useState, type ReactNode } from "react";
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
import { Button, ErroFaixa, Field, Input, SectionCard } from "@/components/ui";
import { SectionIcon } from "@/lib/section-icons";
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
 *
 * ── A forma da tela ──────────────────────────────────────────────────────────
 * Um assunto por cartão (`SectionCard`), em três grupos rotulados. A edição tem
 * dezesseis controles; empilhados em dois cartões grandes eles se liam como uma
 * lista contínua, e três "Fundo" na mesma coluna só se distinguiam contando de
 * cima para baixo. Os grupos existem porque as duas metades respondem a
 * perguntas diferentes: "como o corte é montado" e "que marca ele carrega".
 */

const NICHES = [...PUBLIC_NICHES, ...PERSONAL_NICHES];

interface Props {
  /** Ausente = criar. Presente = editar. */
  profile?: Profile;
}

/**
 * Rótulo de grupo: separa os três assuntos sem virar mais uma caixa.
 *
 * O rótulo é um parágrafo, e não um cabeçalho, para não abrir um nível entre o
 * título da página e os cartões — cada cartão é uma seção de verdade, com seu
 * `h2`. O grupo é uma pista visual, e chega ao leitor de tela como nome da
 * região, via `aria-labelledby`.
 */
function Grupo({ titulo, children }: { titulo: string; children: ReactNode }) {
  const id = useId();
  return (
    <section aria-labelledby={id} className="flex flex-col gap-3">
      <p
        id={id}
        className="text-label font-medium uppercase tracking-[0.14em] text-ink-muted"
      >
        {titulo}
      </p>
      {children}
    </section>
  );
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

  const basicos = (
    <SectionCard
      icon="identidade"
      title="Informações básicas"
      description="O nome que você vê na lista e o critério com que os vídeos deste perfil são analisados."
    >
      <div className="grid gap-4 sm:grid-cols-2">
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
            <p className="text-label leading-relaxed text-ink-muted">
              {nicho.description}
            </p>
          )}
        </Field>
      </div>
    </SectionCard>
  );

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
        {soOEssencial ? (
          basicos
        ) : (
          /* ── Edição: os blocos à esquerda, a prévia à direita ───────────
             Estes controles não fazem sentido sem ver o que mudam. Enquanto
             moravam numa coluna de painéis soltos, escolher uma cor de banner
             era escolher no escuro — o resultado só aparecia depois de gastar
             crédito num vídeo. */
          <div className="grid grid-cols-[minmax(0,1fr)] gap-4 lg:grid-cols-[minmax(0,1fr)_15rem] lg:items-start lg:gap-6">
            {/* ── Prévia ───────────────────────────────────────────────────
                Primeira no DOM e grudada no topo: no celular ela é uma tira
                fina que acompanha a rolagem, porque uma prévia que só aparece
                depois de todos os controles não serve para nada — a pessoa
                mexe na cor aqui e o resultado está três telas abaixo.
                No desktop a mesma marcação vira o cartão da coluna direita. */}
            <aside className="sticky top-0 z-20 -mx-4 min-w-0 border-b border-line bg-base px-4 py-3 sm:-mx-6 sm:px-6 lg:order-2 lg:top-6 lg:mx-0 lg:rounded-md lg:border lg:border-line lg:bg-raised lg:p-4">
              <header className="mb-4 hidden items-start gap-3 lg:flex">
                <span className="flex h-9 w-9 flex-shrink-0 items-center justify-center rounded-sm border border-line bg-inset text-mint">
                  <SectionIcon name="previa" />
                </span>
                <div className="min-w-0">
                  <h2 className="text-body font-medium text-ink">Prévia</h2>
                  <p className="mt-0.5 text-label leading-relaxed text-ink-muted">
                    Atualiza enquanto você mexe.
                  </p>
                </div>
              </header>

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
                {/* No celular a tira tem que caber numa linha de leitura;
                    o porquê completo fica onde há espaço para ele. */}
                <p className="min-w-0 text-label leading-relaxed text-ink-dim lg:mt-3">
                  <span className="lg:hidden">Atualiza enquanto você mexe.</span>
                  <span className="hidden lg:inline">
                    Proporções, posição e cor são as do arquivo final. A quebra
                    de linha do título é aproximada — quem quebra de verdade é o
                    servidor, com a fonte instalada nele.
                  </span>
                </p>
              </div>

              <p className="mt-4 hidden rounded-sm border border-line bg-inset px-3 py-2 text-label leading-relaxed text-ink-muted lg:block">
                Nada aqui vale antes de salvar, e o que você salvar entra nos
                próximos clipes — os que já foram gerados continuam como estão.
              </p>
            </aside>

            <div className="flex min-w-0 flex-col gap-6 lg:order-1">
              <Grupo titulo="Perfil">
                {basicos}
                <SectionCard
                  icon="icone"
                  title="Ícone do perfil"
                  description="Para bater o olho e achar este perfil na lista. Não aparece no clipe."
                >
                  {/* Grade de seis, e não uma fileira que quebra: em 390px os
                      seis botões de 48px não cabiam numa linha e o último caía
                      sozinho embaixo, parecendo de outro grupo. */}
                  <div className="grid grid-cols-6 gap-2 sm:max-w-xs">
                    {AVATARS.map((chave) => (
                      <button
                        key={chave}
                        type="button"
                        onClick={() => setAvatar(chave)}
                        title={AVATAR_LABEL[chave]}
                        aria-label={AVATAR_LABEL[chave]}
                        aria-pressed={avatar === chave}
                        className={`flex aspect-square items-center justify-center rounded-sm border transition-colors ${
                          avatar === chave
                            ? "border-mint bg-mint-soft text-mint"
                            : "border-line bg-inset text-ink-dim hover:border-line-strong hover:text-ink"
                        }`}
                      >
                        <AvatarIcon name={chave} className="h-5 w-5" />
                      </button>
                    ))}
                  </div>
                </SectionCard>
              </Grupo>

              <Grupo titulo="Padrão de geração">
                <SectionCard
                  icon="layout"
                  title="Layout do clipe"
                  description="Como o vertical é montado. Vem escolhido no formulário de geração e dá para trocar em cada vídeo."
                >
                  <LayoutModeSelector
                    value={layout}
                    onChange={setLayout}
                    source={sourceType}
                  />
                </SectionCard>

                <SectionCard
                  icon="legenda"
                  title="Legenda"
                  description="Como a fala aparece na tela de quem assiste sem som."
                >
                  <SubtitleModeSelector value={subtitle} onChange={setSubtitle} />
                </SectionCard>
              </Grupo>

              <Grupo titulo="Identidade">
                {editando && brandBase === null ? (
                  <p className="rounded-md border border-line bg-raised p-4 text-body text-ink-dim sm:p-5">
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
              </Grupo>
            </div>
          </div>
        )}

        {erro && <ErroFaixa>{erro}</ErroFaixa>}

        {!soOEssencial && (
          <p className="text-label leading-relaxed text-ink-muted lg:hidden">
            Nada aqui vale antes de salvar, e o que você salvar entra nos
            próximos clipes — os que já foram gerados continuam como estão.
          </p>
        )}

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
