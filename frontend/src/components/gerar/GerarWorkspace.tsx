"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Check, ChevronDown, Clock3, Loader2, Play, SlidersHorizontal } from "lucide-react";

import ClipModeSelector from "@/components/ClipModeSelector";
import CreditConfirm from "@/components/CreditConfirm";
import LowBalanceBanner from "@/components/LowBalanceBanner";
import ManualClipsField from "@/components/ManualClipsField";
import SourceTypeSelector from "@/components/SourceTypeSelector";
import { duracao } from "@/components/ProjectRow";
import { buttonClass, PageHeader, StepHeader } from "@/components/ui/editorial";
import {
  createJob,
  createProfile,
  estimateJob,
  getApiErrorMessage,
  getVideoMetadata,
  listProfiles,
} from "@/lib/api";
import { IS_PUBLIC_BUILD } from "@/lib/build";
import { defaultStyle, type ClipStyle } from "@/lib/clipStyle";
import { avisarSaldoMudou } from "@/lib/creditos";
import { PUBLIC_NICHES } from "@/lib/features";
import { LAYOUT_LABELS, LAYOUT_RUBRICS, layoutAllowed, layoutsFor } from "@/lib/layouts";
import type { ClipMode, CreateJobPayload, Estimate, LayoutMode, ManualMode, Profile, SourceType } from "@/lib/types";
import { INVALID_YOUTUBE_URL_MESSAGE, isValidYouTubeUrl } from "@/lib/youtube";
import { PERSONAL_NICHES } from "@/personal";

import CaptionPicker from "./CaptionPicker";
import ContextPanel, { type MetaState, type ResumoLinha } from "./ContextPanel";
import CoverUpload, { type CapaEnviada } from "./CoverUpload";
import LayoutPicker from "./LayoutPicker";
import VideoLinkField from "./VideoLinkField";
import { captionChoice, captionChoiceFor, styleWithChoice, type CaptionChoice } from "./choices";

const NICHES = [...PUBLIC_NICHES, ...PERSONAL_NICHES];
const TODOS_OS_LAYOUTS = Object.keys(LAYOUT_RUBRICS) as LayoutMode[];

/**
 * O palpite de rubrica a partir do layout, para quem gera sem perfil.
 *
 * Tela cheia e capa seguem um rosto falando (podcast); a facecam empilhada pede
 * uma câmera separada do jogo (gameplay). Crop e original não presumem nada, e
 * por isso não mexem na rubrica.
 */
function rubricaDoLayout(layout: LayoutMode): SourceType | null {
  if (layout === "streamer") return "gameplay";
  if (layout === "fullscreen" || layout === "cover") return "podcast";
  return null;
}

/**
 * Gerar clipes: colar, escolher o visual, gerar.
 *
 * Funciona SEM perfil — a API sempre aceitou `profile_id` opcional. Escolher um
 * perfil (ou salvar estas escolhas como um) fica em "Configurações extras": ele
 * preenche rubrica, layout e legenda, e manda o estilo da marca junto.
 *
 * O pedido é o `POST /api/jobs` de sempre. O que esta tela acrescenta é conferir
 * o vídeo antes (`GET /api/videos/metadata`) e escolher o destaque da legenda por
 * job (`caption_style`), que muda só a cópia do estilo que o job guarda.
 */
export default function GerarWorkspace({ perfilInicial }: { perfilInicial?: string }) {
  const router = useRouter();

  // ── O vídeo ────────────────────────────────────────────────────────────────
  const [url, setUrl] = useState("");
  const [urlErro, setUrlErro] = useState("");
  const [meta, setMeta] = useState<MetaState>({ status: "idle" });
  const urlLimpa = url.trim();
  const urlValida = isValidYouTubeUrl(urlLimpa);

  useEffect(() => {
    setUrlErro("");
    if (!urlValida) {
      setMeta({ status: "idle" });
      return;
    }
    setMeta({ status: "loading" });
    const controle = new AbortController();
    // Espera a pessoa parar de digitar: cada consulta sai do servidor para o YouTube.
    const t = setTimeout(async () => {
      try {
        const dados = await getVideoMetadata(urlLimpa, controle.signal);
        setMeta(dados.ok ? { status: "ok", data: dados } : { status: "unavailable" });
      } catch (err) {
        if (controle.signal.aborted) return;
        const status = (err as { response?: { status?: number } })?.response?.status;
        setMeta(
          status === 422
            ? { status: "error", message: getApiErrorMessage(err, "Este vídeo não pode ser usado.") }
            : { status: "unavailable" },
        );
      }
    }, 450);
    return () => {
      clearTimeout(t);
      controle.abort();
    };
  }, [urlLimpa, urlValida]);

  // ── Perfil (opcional) ──────────────────────────────────────────────────────
  const [perfis, setPerfis] = useState<Profile[] | null>(null);
  const [perfilId, setPerfilId] = useState<string>("");
  const [perfilAusente, setPerfilAusente] = useState(false);
  const perfil = useMemo(() => perfis?.find((p) => p.id === perfilId) ?? null, [perfis, perfilId]);

  // ── Escolhas ───────────────────────────────────────────────────────────────
  const [legenda, setLegenda] = useState<CaptionChoice>("caixa");
  const [layout, setLayout] = useState<LayoutMode>("fullscreen");
  const [rubrica, setRubrica] = useState<SourceType>("podcast");
  const [rubricaEscolhida, setRubricaEscolhida] = useState(false);
  const [clipMode, setClipMode] = useState<ClipMode>("individual");
  // O gancho de abertura. A última escolha fica lembrada neste navegador: quem
  // gosta de abrir com o gancho não deveria ter de marcar a cada vídeo.
  const [gancho, setGancho] = useState(false);
  useEffect(() => {
    try {
      setGancho(localStorage.getItem("cm-gancho") === "1");
    } catch {
      /* sem armazenamento: começa desligado */
    }
  }, []);
  function escolherGancho(ligado: boolean) {
    setGancho(ligado);
    try {
      localStorage.setItem("cm-gancho", ligado ? "1" : "0");
    } catch {
      /* só não fica lembrado */
    }
  }
  const [trechos, setTrechos] = useState("");
  const [trechosModo, setTrechosModo] = useState<ManualMode>("only");
  const [extrasAbertos, setExtrasAbertos] = useState(false);
  // A capa enviada (só no layout "cover"). Fica guardada se a pessoa olhar outro
  // layout e voltar; só vai no pedido quando o layout é o de capa.
  const [capa, setCapa] = useState<CapaEnviada | null>(null);
  const [enviandoCapa, setEnviandoCapa] = useState(false);
  useEffect(() => {
    const url = capa?.url;
    return () => {
      if (url) URL.revokeObjectURL(url);
    };
  }, [capa?.url]);
  const capaValendo = layout === "cover" ? capa : null;

  /** Aplica o que o perfil diz: rubrica, layout e legenda. */
  const aplicarPerfil = useCallback((p: Profile | null) => {
    if (!p) return;
    setRubrica(p.source_type);
    setRubricaEscolhida(true);
    setLayout(
      layoutAllowed(p.default_layout_mode, p.source_type)
        ? p.default_layout_mode
        : layoutsFor(p.source_type)[0],
    );
    setLegenda(captionChoiceFor(p.default_subtitle_mode, p.style));
  }, []);

  useEffect(() => {
    listProfiles()
      .then((lista) => {
        setPerfis(lista);
        if (perfilInicial) {
          const achado = lista.find((p) => p.id === perfilInicial);
          if (achado) {
            setPerfilId(achado.id);
            aplicarPerfil(achado);
          } else {
            setPerfilAusente(true);
          }
          return;
        }
        // Sem perfil pedido, a página abre com o último que gerou alguma coisa:
        // quem tem um canal só não precisa escolhê-lo de novo a cada vídeo.
        const ultimo = lista
          .filter((p) => p.last_generated_at)
          .sort((a, b) => Date.parse(b.last_generated_at!) - Date.parse(a.last_generated_at!))[0];
        if (ultimo) {
          setPerfilId(ultimo.id);
          aplicarPerfil(ultimo);
        }
      })
      .catch(() => setPerfis([]));
  }, [perfilInicial, aplicarPerfil]);

  function escolherPerfil(id: string) {
    setPerfilId(id);
    const p = perfis?.find((x) => x.id === id) ?? null;
    if (p) aplicarPerfil(p);
    else setRubricaEscolhida(false);
  }

  // Sem perfil e sem rubrica escolhida à mão, todos os layouts aparecem e o
  // layout escolhido sugere a rubrica. Com perfil ou rubrica escolhida, só os que
  // ela aceita — o servidor recusaria os outros.
  const layoutsDisponiveis = useMemo(
    () => (perfil || rubricaEscolhida ? layoutsFor(perfil?.source_type ?? rubrica) : TODOS_OS_LAYOUTS),
    [perfil, rubricaEscolhida, rubrica],
  );

  useEffect(() => {
    if (!layoutsDisponiveis.includes(layout)) setLayout(layoutsDisponiveis[0]);
  }, [layoutsDisponiveis, layout]);

  function escolherLayout(novo: LayoutMode) {
    setLayout(novo);
    if (!perfil && !rubricaEscolhida) {
      const palpite = rubricaDoLayout(novo);
      if (palpite) setRubrica(palpite);
    }
  }

  function escolherRubrica(nova: SourceType) {
    setRubrica(nova);
    setRubricaEscolhida(true);
  }

  // O estilo que a prévia mostra: o do perfil (ou o padrão) com o destaque escolhido.
  const estiloBase: ClipStyle = useMemo(() => perfil?.style ?? defaultStyle(), [perfil]);
  const estilo = useMemo(() => styleWithChoice(estiloBase, legenda), [estiloBase, legenda]);
  const escolhaLegenda = captionChoice(legenda);
  const rubricaEfetiva = perfil?.source_type ?? rubrica;

  // ── Salvar como perfil ─────────────────────────────────────────────────────
  const [nomeNovoPerfil, setNomeNovoPerfil] = useState("");
  const [salvandoPerfil, setSalvandoPerfil] = useState(false);
  const [erroPerfil, setErroPerfil] = useState("");

  async function salvarComoPerfil() {
    const nome = nomeNovoPerfil.trim();
    if (!nome) return;
    setSalvandoPerfil(true);
    setErroPerfil("");
    try {
      const novo = await createProfile({
        name: nome,
        source_type: rubricaEfetiva,
        avatar: null,
        default_layout_mode: layout,
        default_subtitle_mode: escolhaLegenda.mode,
        style: estilo,
      });
      setPerfis((atual) => [...(atual ?? []), novo]);
      setPerfilId(novo.id);
      setNomeNovoPerfil("");
    } catch (err) {
      setErroPerfil(getApiErrorMessage(err, "Não foi possível salvar o perfil."));
    } finally {
      setSalvandoPerfil(false);
    }
  }

  // ── Envio ──────────────────────────────────────────────────────────────────
  const [enviando, setEnviando] = useState(false);
  const [enviado, setEnviado] = useState(false);
  const [erro, setErro] = useState("");
  const [pendente, setPendente] = useState<CreateJobPayload | null>(null);
  const [estimativa, setEstimativa] = useState<Estimate | null>(null);
  const [medindo, setMedindo] = useState(false);
  const [erroEstimativa, setErroEstimativa] = useState("");

  function montarPedido(): CreateJobPayload {
    return {
      profile_id: perfil?.id,
      youtube_url: urlLimpa,
      subtitle_mode: escolhaLegenda.mode,
      caption_style: escolhaLegenda.estilo,
      layout_mode: layout,
      // O nicho do perfil vence: é o que impede gerar com a identidade de outro.
      source_type: rubricaEfetiva,
      clip_mode: clipMode,
      opening_hook: gancho,
      manual_clips: trechos.trim() || undefined,
      manual_mode: trechosModo,
      cover_upload_id: capaValendo?.id,
    };
  }

  async function enviar(pedido: CreateJobPayload) {
    setEnviando(true);
    setErro("");
    try {
      const job = await createJob(pedido);
      // A reserva já saiu do saldo: o número na navegação precisa acompanhar.
      avisarSaldoMudou();
      setEnviado(true);
      router.push(`/jobs/${job.id}`);
    } catch (err) {
      setPendente(null);
      setErro(getApiErrorMessage(err, "Não foi possível iniciar a geração."));
      setEnviando(false);
    }
  }

  async function gerar(e: React.FormEvent) {
    e.preventDefault();
    if (enviando || enviado) return;
    setErro("");
    if (enviandoCapa) {
      setErro("Espere a capa terminar de enviar.");
      return;
    }
    if (!urlLimpa) {
      setUrlErro("Cole o link de um vídeo do YouTube.");
      document.getElementById("cm-url")?.focus();
      return;
    }
    if (!urlValida) {
      setUrlErro(INVALID_YOUTUBE_URL_MESSAGE);
      document.getElementById("cm-url")?.focus();
      return;
    }

    const pedido = montarPedido();

    // Versão pessoal: não há crédito, não há o que confirmar.
    if (!IS_PUBLIC_BUILD) {
      await enviar(pedido);
      return;
    }

    setPendente(pedido);
    setEstimativa(null);
    setErroEstimativa("");
    setMedindo(true);
    try {
      setEstimativa(await estimateJob(pedido.youtube_url));
    } catch (err) {
      // O 422 daqui é o mesmo que a criação daria (live, vídeo acima do teto).
      setErroEstimativa(getApiErrorMessage(err, "Não foi possível medir este vídeo."));
    } finally {
      setMedindo(false);
    }
  }

  // ── Resumo do painel ───────────────────────────────────────────────────────
  const nichoAtual = NICHES.find((n) => n.source === rubricaEfetiva);
  const resumo: ResumoLinha[] = [
    { rotulo: "Legenda", valor: escolhaLegenda.nome },
    { rotulo: "Layout", valor: LAYOUT_LABELS[layout].nome },
    perfil
      ? { rotulo: "Perfil", valor: perfil.name }
      : { rotulo: "Rubrica", valor: nichoAtual?.title ?? rubricaEfetiva },
    {
      rotulo: "Formato",
      valor: trechos.trim()
        ? trechosModo === "only"
          ? "Só os trechos indicados"
          : "Trechos indicados + IA"
        : (clipMode === "compilation" ? "Compilado" : "Clipes individuais") +
          (gancho ? " · com gancho" : ""),
    },
  ];

  const extrasAtivos = [
    perfil ? `Perfil: ${perfil.name}` : null,
    !perfil && rubricaEscolhida ? nichoAtual?.title : null,
    clipMode === "compilation" ? "Compilado" : null,
    trechos.trim() ? "Trechos manuais" : null,
  ].filter(Boolean) as string[];

  const metaDuracao = meta.status === "ok" ? duracao(meta.data.duration_seconds) : null;

  // O botão de gerar nunca some. No xl a coluna da esquerda rola por dentro e o
  // botão é o pé fixo dela. Abaixo disso a página rola inteira e o botão fica
  // preso ao pé da tela até o lugar dele aparecer; o marcador logo abaixo dele
  // diz quando ele "descolou" — aí some a sombra.
  const fimDoBotao = useRef<HTMLDivElement>(null);
  const [preso, setPreso] = useState(false);
  useEffect(() => {
    const alvo = fimDoBotao.current;
    if (!alvo || typeof IntersectionObserver === "undefined") return;
    // Um lote pode trazer mais de uma mudança; vale a mais recente.
    const obs = new IntersectionObserver((entradas) => {
      const e = entradas[entradas.length - 1];
      setPreso(!e.isIntersecting && e.boundingClientRect.top > 0);
    });
    obs.observe(alvo);
    return () => obs.disconnect();
  }, []);

  // A coluna avisa que há mais opções abaixo: a barra de rolagem fica à vista e
  // o pé esmaece enquanto ainda falta conteúdo para ver.
  const rolagem = useRef<HTMLDivElement>(null);
  const conteudo = useRef<HTMLDivElement>(null);
  const [maisAbaixo, setMaisAbaixo] = useState(false);
  const medirRolagem = useCallback(() => {
    const el = rolagem.current;
    if (!el) return;
    setMaisAbaixo(el.scrollHeight - el.scrollTop - el.clientHeight > 4);
  }, []);
  useEffect(() => {
    medirRolagem();
    if (typeof ResizeObserver === "undefined") return;
    const obs = new ResizeObserver(medirRolagem);
    if (rolagem.current) obs.observe(rolagem.current);
    if (conteudo.current) obs.observe(conteudo.current);
    return () => obs.disconnect();
  }, [medirRolagem]);

  function alternarExtras() {
    if (extrasAbertos) setExtrasAbertos(false);
    else abrirExtras();
  }

  /** Abre as configurações extras e as traz para a vista — dentro do painel, ou na página. */
  function abrirExtras(focar?: string) {
    setExtrasAbertos(true);
    requestAnimationFrame(() => {
      if (focar) document.getElementById(focar)?.focus({ preventScroll: true });
      const secao = document.getElementById("cm-extras-secao");
      const painel = rolagem.current;
      if (!secao || !painel) return;
      // Com a coluna rolando por dentro, rola só ela: scrollIntoView arrastaria
      // a página junto.
      if (painel.scrollHeight > painel.clientHeight) {
        const topo =
          secao.getBoundingClientRect().top - painel.getBoundingClientRect().top + painel.scrollTop - 12;
        painel.scrollTo({ top: topo, behavior: "smooth" });
      } else if (getComputedStyle(painel).overflowY === "visible") {
        secao.scrollIntoView({ block: "start", behavior: "smooth" });
      }
    });
  }
  const bloqueado = meta.status === "error" || (meta.status === "ok" && meta.data.is_live);

  return (
    <div className="grid min-h-screen grid-cols-[minmax(0,1fr)] xl:h-dvh xl:min-h-0 xl:grid-cols-[minmax(0,1.08fr)_minmax(0,1fr)] xl:overflow-hidden">
      {/* ── Coluna de geração ───────────────────────────────────────────────
          No xl a coluna inteira rola por dentro, separada do painel da direita,
          e o botão de gerar é o pé fixo dela. Abaixo disso a página rola e o
          botão fica preso ao pé da tela. */}
      <form
        onSubmit={gerar}
        noValidate
        aria-label="Configurar e gerar"
        className="flex min-w-0 flex-col pb-7 xl:h-dvh xl:pb-0"
      >
        <div
          ref={rolagem}
          onScroll={medirRolagem}
          className="cm-scroll relative px-4 pt-6 sm:px-8 lg:px-12 lg:pt-7 xl:min-h-0 xl:flex-initial xl:overflow-y-auto xl:pb-4 xl:pr-6"
        >
          <PageHeader
            variant="display"
            eyebrow="Novo projeto"
            title="Gerar clipes"
            description="Cole o link, configure o estilo e receba clipes prontos para postar."
          />

          {perfilAusente && (
            <p className="mt-3 rounded-md border border-line bg-raised px-4 py-3 text-body text-ink-dim">
              O perfil pedido não existe mais. Você pode gerar sem perfil ou escolher outro em
              Configurações extras.
            </p>
          )}

          <div ref={conteudo} className="mt-4 flex flex-col gap-2.5">
            {/* 01 — link */}
            <section className="rounded-lg bg-inset px-4 py-3.5 sm:px-6">
              <StepHeader number="01" title="Link do vídeo" id="cm-passo-1" />
              <div className="mt-3">
                <VideoLinkField
                  value={url}
                  onChange={setUrl}
                  error={urlErro}
                  disabled={enviando}
                  labelledBy="cm-passo-1"
                />
              </div>
            </section>

            {/* 02 — legenda */}
            <section className="rounded-lg bg-inset px-4 py-3.5 sm:px-6">
              <StepHeader
                number="02"
                title="Tipo de legenda"
                id="cm-passo-2"
                aside={<span className="hidden text-label text-ink-muted sm:inline">{escolhaLegenda.descricao}</span>}
              />
              <div className="mt-2.5">
                <CaptionPicker value={legenda} onChange={setLegenda} style={estiloBase} labelledBy="cm-passo-2" />
              </div>
            </section>

            {/* 03 — layout */}
            <section className="rounded-lg bg-inset px-4 py-3.5 sm:px-6">
              <StepHeader
                number="03"
                title="Layout do clipe"
                id="cm-passo-3"
                aside={
                  <span className="hidden max-w-[16rem] truncate text-label text-ink-muted sm:inline">
                    {LAYOUT_LABELS[layout].descricao}
                  </span>
                }
              />
              <div className="mt-2.5">
                <LayoutPicker
                  value={layout}
                  onChange={escolherLayout}
                  available={layoutsDisponiveis}
                  labelledBy="cm-passo-3"
                />
              </div>
              {layout === "cover" && (
                <div className="mt-3">
                  <CoverUpload value={capa} onChange={setCapa} onUploading={setEnviandoCapa} />
                </div>
              )}
            </section>

            {/* 04 — gancho de abertura */}
            <section className="rounded-lg bg-inset px-4 py-3.5 sm:px-6">
              <div className="flex items-start justify-between gap-4">
                <div className="min-w-0">
                  <StepHeader number="04" title="Gancho de abertura" id="cm-passo-4" />
                  <p id="cm-gancho-desc" className="mt-1.5 text-body text-ink-dim">
                    Os primeiros segundos mostram a fala mais forte do clipe — tipo
                    &ldquo;pronto, morremo&rdquo; — e então ele começa do início.
                  </p>
                </div>
                <label htmlFor="cm-gancho" className="relative mt-0.5 inline-flex flex-shrink-0 cursor-pointer">
                  <input
                    id="cm-gancho"
                    type="checkbox"
                    role="switch"
                    checked={gancho}
                    onChange={(e) => escolherGancho(e.target.checked)}
                    aria-labelledby="cm-passo-4"
                    aria-describedby="cm-gancho-desc"
                    className="peer sr-only"
                  />
                  <span
                    aria-hidden
                    className="h-6 w-11 rounded-full bg-line-strong transition-colors peer-checked:bg-ink peer-focus-visible:outline peer-focus-visible:outline-2 peer-focus-visible:outline-offset-2 peer-focus-visible:outline-ink"
                  />
                  <span
                    aria-hidden
                    className="absolute left-0.5 top-0.5 h-5 w-5 rounded-full bg-raised shadow-sm transition-transform peer-checked:translate-x-5 peer-checked:bg-mint-strong"
                  />
                </label>
              </div>
            </section>

            {/* Configurações extras */}
            <section
              id="cm-extras-secao"
              className="scroll-mt-20 rounded-lg border border-line bg-raised xl:scroll-mt-3"
            >
              <button
                type="button"
                onClick={alternarExtras}
                aria-expanded={extrasAbertos}
                aria-controls="cm-extras"
                className="flex w-full items-center gap-3.5 rounded-lg px-4 py-3.5 text-left sm:px-6"
              >
                <SlidersHorizontal className="h-5 w-5 flex-shrink-0 text-ink" aria-hidden />
                <span className="flex min-w-0 flex-1 flex-col sm:flex-row sm:items-center sm:gap-3">
                  <span className="text-[0.9375rem] font-medium text-ink">Configurações extras</span>
                  {extrasAtivos.length > 0 && (
                    <span className="truncate text-label text-ink-muted">{extrasAtivos.join(" · ")}</span>
                  )}
                </span>
                <ChevronDown
                  className={`h-5 w-5 flex-shrink-0 text-ink-dim transition-transform duration-200 ${
                    extrasAbertos ? "rotate-180" : ""
                  }`}
                  aria-hidden
                />
              </button>

              <div
                id="cm-extras"
                hidden={!extrasAbertos}
                className="flex flex-col gap-6 border-t border-line px-4 pb-6 pt-5 sm:px-6"
              >
                {/* Perfil */}
                <div className="flex flex-col gap-2">
                  <label htmlFor="cm-perfil" className="text-body font-medium text-ink-dim">
                    Perfil
                  </label>
                  <div className="flex flex-wrap items-center gap-2">
                    <select
                      id="cm-perfil"
                      value={perfilId}
                      onChange={(e) => escolherPerfil(e.target.value)}
                      disabled={perfis === null}
                      className="min-h-10 min-w-[14rem] rounded-md border border-line bg-raised px-3 text-body text-ink focus:border-ink"
                    >
                      <option value="">Sem perfil</option>
                      {(perfis ?? []).map((p) => (
                        <option key={p.id} value={p.id}>
                          {p.name}
                        </option>
                      ))}
                    </select>
                    {perfil && (
                      <Link
                        href={`/perfis/${perfil.id}/editar`}
                        className="text-body font-medium text-ink underline decoration-line-strong underline-offset-4 hover:decoration-ink"
                      >
                        Editar estilo do perfil
                      </Link>
                    )}
                  </div>
                  <p className="text-label text-ink-dim">
                    {perfil
                      ? "O perfil define a rubrica e a marca (cores, fonte, @) dos clipes."
                      : "Sem perfil, os clipes saem no estilo padrão do ClipMint."}
                  </p>

                  {!perfil && (
                    <div className="mt-2 flex flex-col gap-2 rounded-md border border-dashed border-line-strong p-3.5">
                      <label htmlFor="cm-novo-perfil" className="text-label font-semibold text-ink">
                        Salvar estas escolhas como perfil
                      </label>
                      <div className="flex flex-wrap gap-2">
                        <input
                          id="cm-novo-perfil"
                          value={nomeNovoPerfil}
                          onChange={(e) => setNomeNovoPerfil(e.target.value)}
                          placeholder="Nome do perfil (ex.: o nome do canal)"
                          maxLength={60}
                          className="min-h-10 min-w-0 flex-1 rounded-md border border-line bg-raised px-3 text-body text-ink placeholder:text-ink-muted focus:border-ink"
                        />
                        <button
                          type="button"
                          onClick={salvarComoPerfil}
                          disabled={!nomeNovoPerfil.trim() || salvandoPerfil}
                          className={buttonClass("secondary")}
                        >
                          {salvandoPerfil ? "Salvando..." : "Salvar perfil"}
                        </button>
                      </div>
                      {erroPerfil && <p className="text-label text-danger">{erroPerfil}</p>}
                    </div>
                  )}
                </div>

                {!perfil && (
                  <SourceTypeSelector
                    value={rubrica}
                    onChange={escolherRubrica}
                    isInferred={!rubricaEscolhida}
                  />
                )}

                <ClipModeSelector value={clipMode} onChange={setClipMode} />

                <ManualClipsField
                  value={trechos}
                  onChange={setTrechos}
                  mode={trechosModo}
                  onModeChange={setTrechosModo}
                  isCompilation={clipMode === "compilation"}
                />
              </div>
            </section>

            {IS_PUBLIC_BUILD && <LowBalanceBanner />}
          </div>

          {/* Esmaecido no pé da coluna: ainda há opções abaixo. */}
          <div
            aria-hidden
            className={`pointer-events-none sticky bottom-0 -mb-4 hidden h-10 bg-gradient-to-t from-base to-transparent transition-opacity duration-200 xl:-mt-10 xl:block ${
              maisAbaixo ? "opacity-100" : "opacity-0"
            }`}
          />
        </div>

        {/* O botão de gerar: pé fixo da coluna (xl) ou preso ao pé da tela */}
        <div
          className={`sticky bottom-0 z-20 mt-3 border-t px-4 pb-[max(0.75rem,env(safe-area-inset-bottom))] pt-3 transition-[background-color,box-shadow] duration-200 sm:px-8 lg:px-12 xl:static xl:mt-0 xl:border-line xl:bg-base xl:pb-5 xl:pr-8 ${
            preso
              ? "border-line bg-base/92 shadow-[0_-10px_28px_-18px_rgba(36,36,36,0.45)] backdrop-blur-md xl:shadow-none xl:backdrop-blur-none"
              : "border-transparent"
          }`}
        >
          <button
            type="submit"
            disabled={enviando || enviado || bloqueado}
            aria-describedby={erro ? "cm-erro-envio" : undefined}
            className={`${buttonClass("create", "lg")} w-full gap-0 px-0 text-[1.3125rem]`}
          >
            <span className="flex flex-1 items-center justify-center gap-3 whitespace-nowrap px-6">
              {enviado ? (
                <Check className="h-6 w-6" strokeWidth={3} aria-hidden />
              ) : enviando ? (
                <Loader2 className="h-6 w-6 animate-spin" aria-hidden />
              ) : (
                <Play className="h-6 w-6 fill-current" aria-hidden />
              )}
              {enviado
                ? "Enviado — abrindo o projeto"
                : enviando
                  ? "Enviando..."
                  : clipMode === "compilation"
                    ? "Gerar compilado"
                    : "Gerar clipes"}
            </span>
            {metaDuracao && !enviando && !enviado && (
              <span
                className="hidden items-center gap-2 self-stretch border-l border-white/35 px-5 text-body font-semibold sm:flex"
                title="Duração do vídeo de origem"
              >
                <Clock3 className="h-[1.125rem] w-[1.125rem]" aria-hidden />
                <span className="tabular">{metaDuracao}</span>
                <span className="sr-only">de vídeo</span>
              </span>
            )}
          </button>
          {erro && (
            <p id="cm-erro-envio" role="alert" className="mt-3 rounded-md border border-danger/30 bg-danger-soft px-4 py-3 text-body text-danger">
              {erro}
            </p>
          )}
        </div>
        <div ref={fimDoBotao} aria-hidden className="h-px xl:hidden" />
      </form>

      {/* ── Painel contextual ─────────────────────────────────────────────── */}
      {/* No xl ele não rola: cabe inteiro na altura da janela. */}
      <aside
        aria-label="Prévia e projetos"
        className="min-w-0 border-t border-line px-4 pb-12 pt-8 sm:px-8 lg:px-12 xl:flex xl:h-dvh xl:flex-col xl:overflow-hidden xl:border-t-0 xl:pb-6 xl:pl-6 xl:pr-10 xl:pt-8"
      >
        <ContextPanel
          urlValida={urlValida}
          url={urlLimpa}
          meta={meta}
          resumo={resumo}
          style={estilo}
          layout={layout}
          mode={escolhaLegenda.mode}
          perfil={perfil?.name ?? null}
          onTrocarPerfil={() => abrirExtras("cm-perfil")}
          coverUrl={capaValendo?.url ?? null}
        />
      </aside>

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

