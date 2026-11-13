"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { AlertTriangle, ArrowRight, CaseSensitive, Clock3, FolderOpen, PanelsTopLeft, Radio, Scissors } from "lucide-react";

import ClipPreview from "@/components/ClipPreview";
import ProjectRow, { duracao } from "@/components/ProjectRow";
import { Eyebrow, SectionLabel } from "@/components/ui/editorial";
import { listJobs } from "@/lib/api";
import type { ClipStyle } from "@/lib/clipStyle";
import type { Job, LayoutMode, SubtitleMode, VideoMetadata } from "@/lib/types";

export type MetaState =
  | { status: "idle" }
  | { status: "loading" }
  | { status: "ok"; data: VideoMetadata }
  | { status: "unavailable" }
  | { status: "error"; message: string };

export interface ResumoLinha {
  rotulo: string;
  valor: string;
}

/**
 * Qual perfil está valendo, logo abaixo da prévia — é ele que dá a cor e a fonte
 * que a prévia mostra. Discreto, mas clicável: leva ao seletor de perfil.
 */
function PerfilDaPrevia({
  nome,
  onTrocar,
  escuro = false,
}: {
  nome: string | null;
  onTrocar: () => void;
  escuro?: boolean;
}) {
  return (
    <button
      type="button"
      onClick={onTrocar}
      title={nome ? `Perfil: ${nome} — trocar` : "Escolher um perfil"}
      className={`group mx-auto mt-2.5 flex max-w-full items-center justify-center gap-1.5 rounded-full px-2 py-0.5 text-[0.6875rem] transition-colors ${
        escuro ? "text-white/70 hover:bg-white/10 hover:text-white" : "text-ink-muted hover:bg-inset hover:text-ink"
      }`}
    >
      <span
        className={`h-1.5 w-1.5 flex-shrink-0 rounded-full ${
          nome ? "bg-mint-strong" : escuro ? "border border-white/50" : "border border-ink-muted"
        }`}
        aria-hidden
      />
      <span className="sr-only">Perfil selecionado: </span>
      <span className="truncate font-medium">{nome ?? "Sem perfil"}</span>
    </button>
  );
}

/**
 * A composição do estado vazio: tipografia, formas e a prévia do estilo escolhido.
 *
 * Sem foto de gente: não há foto própria nem licenciada, e um rosto de terceiro
 * na interface seria usar a imagem de alguém para vender o produto. No lugar dela
 * entra a prévia do clipe — a mesma que a tela de estilo usa, nas medidas do
 * render —, que muda a cada escolha à esquerda. O que se vê é o que sai.
 */
function Composicao({
  style,
  layout,
  mode,
  perfil,
  onTrocarPerfil,
  coverUrl,
}: {
  coverUrl: string | null;
  style: ClipStyle;
  layout: LayoutMode;
  mode: SubtitleMode;
  perfil: string | null;
  onTrocarPerfil: () => void;
}) {
  return (
    // Sangra até a borda de cima e a da direita, como uma página de revista: as
    // margens negativas desfazem o respiro do painel só deste lado. No xl ela
    // encolhe para o painel caber na janela sem rolar; prévia e título medem-se
    // pela altura que sobrou (unidades cqh).
    <div className="relative -mr-4 -mt-8 h-[24rem] overflow-hidden [container-type:size] sm:-mr-8 sm:h-[31rem] lg:-mr-12 xl:-mr-10 xl:h-[32.5rem] xl:min-h-[12rem] xl:shrink">
      {/* O bloco escuro em diagonal, onde mora a prévia */}
      <div
        className="absolute inset-y-0 right-0 w-full bg-sidebar"
        style={{ clipPath: "polygon(38% 0, 100% 0, 100% 100%, 70% 100%)" }}
        aria-hidden
      />
      {/* O corte em coral, na borda */}
      <div
        className="absolute inset-y-0 right-0 w-full bg-coral"
        style={{ clipPath: "polygon(100% 40%, 100% 100%, 82% 100%)" }}
        aria-hidden
      />
      {/* As barras em menta, como marca de corte */}
      <span
        className="cm-slashes absolute left-[37%] top-[13%] text-[2.6rem] sm:text-[3.4rem]"
        style={{ color: "var(--color-mint-strong)" }}
        aria-hidden
      />

      {/* A prévia real do estilo */}
      <figure className="absolute right-[7%] top-[3%] w-[min(38%,13.5rem,40cqh)] sm:right-[9%]">
        <figcaption className="tabular mb-3 text-right text-[0.625rem] uppercase tracking-[0.16em] text-white/75">
          Prévia do seu estilo
        </figcaption>
        <div className="relative">
          <span className="pointer-events-none absolute -inset-2.5 sm:-inset-3" aria-hidden>
            <span className="absolute left-0 top-0 h-3 w-3 border-l-2 border-t-2 border-mint-strong" />
            <span className="absolute right-0 top-0 h-3 w-3 border-r-2 border-t-2 border-mint-strong" />
            <span className="absolute bottom-0 left-0 h-3 w-3 border-b-2 border-l-2 border-mint-strong" />
            <span className="absolute bottom-0 right-0 h-3 w-3 border-b-2 border-r-2 border-mint-strong" />
          </span>
          <div className="overflow-hidden rounded-[6px] shadow-[0_18px_40px_-18px_rgb(0_0_0/0.6)]">
            <ClipPreview style={style} layout={layout} mode={mode} coverUrl={coverUrl} />
          </div>
        </div>
        <PerfilDaPrevia nome={perfil} onTrocar={onTrocarPerfil} escuro />
      </figure>

      {/* O título editorial */}
      <p
        className="absolute bottom-[7%] left-0 font-condensed text-[min(3.75rem,10.5cqh,11cqw)] font-extrabold uppercase italic leading-[0.9] tracking-[-0.01em] text-ink"
      >
        <span className="inline-block bg-mint-strong px-2 pr-3">Cortes</span>
        <br />
        prontos
        <br />
        para o
        <br />
        <span className="relative inline-block">
          seu canal<span className="text-coral">.</span>
          <svg
            viewBox="0 0 200 14"
            preserveAspectRatio="none"
            className="absolute -bottom-3 left-[-4%] h-3 w-[104%]"
            aria-hidden
          >
            <path d="M3 10C52 4 118 2 197 6" fill="none" stroke="var(--color-coral)" strokeWidth="4" strokeLinecap="round" />
          </svg>
        </span>
      </p>
    </div>
  );
}

const TRIO = [
  { icon: Scissors, titulo: "Cortes", texto: "achados por IA" },
  { icon: CaseSensitive, titulo: "Legendas", texto: "no seu estilo" },
  { icon: PanelsTopLeft, titulo: "Layouts", texto: "verticais 9:16" },
];

function Trio() {
  return (
    <ul className="grid grid-cols-3 divide-x divide-line border-y border-line py-4">
      {TRIO.map(({ icon: Icone, titulo, texto }) => (
        <li key={titulo} className="flex items-center gap-2.5 px-3 first:pl-0 sm:gap-3 sm:px-4">
          <Icone className="h-6 w-6 flex-shrink-0 text-ink sm:h-7 sm:w-7" strokeWidth={1.6} aria-hidden />
          <span className="text-label leading-snug text-ink-dim sm:text-body sm:leading-snug">
            <span className="block font-semibold text-ink">{titulo}</span>
            <span className="hidden sm:inline">{texto}</span>
          </span>
        </li>
      ))}
    </ul>
  );
}

/** O vídeo colado, para a pessoa confirmar que é ele antes de gastar tempo. */
function VideoIdentificado({
  meta,
  url,
  resumo,
  style,
  layout,
  mode,
  perfil,
  onTrocarPerfil,
  coverUrl,
}: {
  coverUrl: string | null;
  meta: MetaState;
  url: string;
  resumo: ResumoLinha[];
  style: ClipStyle;
  layout: LayoutMode;
  mode: SubtitleMode;
  perfil: string | null;
  onTrocarPerfil: () => void;
}) {
  const dados = meta.status === "ok" ? meta.data : null;
  const carregando = meta.status === "loading" || meta.status === "idle";
  const dur = duracao(dados?.duration_seconds ?? null);

  return (
    <section
      aria-labelledby="cm-video"
      aria-busy={carregando}
      className="cm-fade-in flex flex-col gap-6 xl:min-h-0 xl:shrink"
    >
      <Eyebrow>
        <span id="cm-video">{carregando ? "Conferindo o vídeo" : "Vídeo identificado"}</span>
      </Eyebrow>

      {/* No xl o bloco encolhe com a janela; miniatura e prévia medem-se pela altura dele. */}
      <div className="xl:h-[18.75rem] xl:min-h-[9rem] xl:shrink xl:[container-type:size]">
        <div className="grid grid-cols-[minmax(0,1fr)_7.5rem] gap-5 sm:grid-cols-[minmax(0,1fr)_9.5rem] sm:gap-6 xl:grid-cols-[minmax(0,1fr)_min(9.5rem,calc((100cqh-2rem)*0.5625))]">
          <div className="min-w-0">
            <div className="relative aspect-video overflow-hidden rounded-lg bg-inset xl:max-w-[calc((100cqh-6rem)*16/9)]">
              {dados?.thumbnail_url ? (
                // eslint-disable-next-line @next/next/no-img-element
                <img src={dados.thumbnail_url} alt="" className="h-full w-full object-cover" />
              ) : (
                <div className={`h-full w-full ${carregando ? "animate-pulse bg-hover" : ""}`} />
              )}
              {dur && (
                <span className="tabular absolute bottom-2 right-2 rounded-sm bg-ink/85 px-1.5 py-0.5 text-label text-white">
                  {dur}
                </span>
              )}
              {dados?.is_live && (
                <span className="absolute left-2 top-2 inline-flex items-center gap-1 rounded-sm bg-danger px-1.5 py-0.5 text-label font-semibold text-white">
                  <Radio className="h-3 w-3" aria-hidden /> Ao vivo
                </span>
              )}
            </div>

            {carregando ? (
              <div className="mt-4 flex flex-col gap-2" aria-hidden>
                <span className="h-5 w-4/5 animate-pulse rounded-sm bg-hover" />
                <span className="h-4 w-2/5 animate-pulse rounded-sm bg-hover" />
              </div>
            ) : dados?.title ? (
              <div className="mt-4">
                <h3 className="line-clamp-2 font-display text-[1.25rem] font-bold leading-tight text-ink">
                  {dados.title}
                </h3>
                <p className="mt-1.5 flex flex-wrap items-center gap-x-2 text-body text-ink-dim">
                  {dados.channel && <span>{dados.channel}</span>}
                  {dados.channel && <span aria-hidden>·</span>}
                  <span>YouTube</span>
                  {dur && (
                    <>
                      <span aria-hidden>·</span>
                      <span className="inline-flex items-center gap-1">
                        <Clock3 className="h-3.5 w-3.5" aria-hidden />
                        <span className="tabular">{dur}</span>
                      </span>
                    </>
                  )}
                </p>
              </div>
            ) : (
              <p className="mt-4 break-all text-body text-ink-dim">{url}</p>
            )}
          </div>

          <div>
            <ClipPreview style={style} layout={layout} mode={mode} coverUrl={coverUrl} />
            <PerfilDaPrevia nome={perfil} onTrocar={onTrocarPerfil} />
          </div>
        </div>
      </div>

      {meta.status === "error" && (
        <p role="alert" className="flex gap-2.5 rounded-md border border-danger/30 bg-danger-soft px-4 py-3 text-body text-danger">
          <AlertTriangle className="mt-0.5 h-4 w-4 flex-shrink-0" aria-hidden />
          {meta.message}
        </p>
      )}
      {meta.status === "unavailable" && (
        <p className="rounded-md border border-line bg-inset px-4 py-3 text-body text-ink-dim">
          Não deu para conferir os dados do vídeo agora. Dá para gerar mesmo assim — o
          projeto tenta de novo ao começar.
        </p>
      )}
      {dados?.is_live && (
        <p role="alert" className="rounded-md border border-running/30 bg-running-soft px-4 py-3 text-body text-running">
          Este link é de uma transmissão ao vivo em andamento. Espere a live acabar e use o
          link da gravação.
        </p>
      )}

      <dl className="grid grid-cols-2 gap-x-6 gap-y-3.5 border-t border-line pt-5">
        {resumo.map((linha) => (
          <div key={linha.rotulo} className="min-w-0">
            <dt className="text-label font-semibold uppercase tracking-[0.1em] text-ink-muted">{linha.rotulo}</dt>
            <dd className="mt-1 truncate text-body font-medium text-ink">{linha.valor}</dd>
          </div>
        ))}
      </dl>
    </section>
  );
}

/** "/// ÚLTIMOS PROJETOS" — os três mais recentes, de verdade. */
function UltimosProjetos() {
  const [jobs, setJobs] = useState<Job[] | null>(null);
  const [falhou, setFalhou] = useState(false);

  const carregar = useCallback(() => {
    listJobs()
      .then((todos) => {
        setJobs(todos.slice(0, 3));
        setFalhou(false);
      })
      .catch(() => setFalhou(true));
  }, []);

  useEffect(() => {
    carregar();
  }, [carregar]);

  return (
    <section aria-labelledby="cm-ultimos" className="flex flex-shrink-0 flex-col gap-4">
      <SectionLabel
        id="cm-ultimos"
        action={
          jobs && jobs.length > 0 ? (
            <Link
              href="/projetos"
              className="group inline-flex items-center gap-1.5 text-body font-semibold text-ink hover:underline"
            >
              Ver todos
              <ArrowRight className="h-4 w-4 text-coral transition-transform duration-150 group-hover:translate-x-0.5" aria-hidden />
            </Link>
          ) : undefined
        }
      >
        Últimos projetos
      </SectionLabel>

      {falhou && <p className="text-body text-ink-dim">Não foi possível carregar os projetos.</p>}
      {!jobs && !falhou && (
        <div className="cm-ultimos flex flex-col gap-2.5" aria-hidden>
          {[0, 1].map((i) => (
            <span key={i} className="h-[4.75rem] animate-pulse rounded-md bg-inset" />
          ))}
        </div>
      )}
      {jobs && jobs.length === 0 && (
        <div className="flex items-center gap-4 rounded-md border border-dashed border-line-strong px-5 py-5">
          <FolderOpen className="h-6 w-6 flex-shrink-0 text-ink-muted" aria-hidden />
          <p className="text-body text-ink-dim">
            Seus projetos aparecem aqui assim que você gerar os primeiros clipes.
          </p>
        </div>
      )}
      {jobs && jobs.length > 0 && (
        <ul className="cm-ultimos flex flex-col gap-2.5">
          {jobs.map((job) => (
            <ProjectRow key={job.id} job={job} compact onDeleted={carregar} />
          ))}
        </ul>
      )}
    </section>
  );
}

export default function ContextPanel({
  urlValida,
  url,
  meta,
  resumo,
  style,
  layout,
  mode,
  perfil,
  onTrocarPerfil,
  coverUrl,
}: {
  /** A capa enviada (layout "cover"), para a prévia mostrar. */
  coverUrl: string | null;
  urlValida: boolean;
  url: string;
  meta: MetaState;
  resumo: ResumoLinha[];
  style: ClipStyle;
  layout: LayoutMode;
  mode: SubtitleMode;
  /** Nome do perfil escolhido; nulo = sem perfil. */
  perfil: string | null;
  onTrocarPerfil: () => void;
}) {
  return (
    <div className="flex flex-col gap-8 xl:min-h-0 xl:flex-1">
      {urlValida ? (
        <VideoIdentificado
          meta={meta}
          url={url}
          resumo={resumo}
          style={style}
          layout={layout}
          mode={mode}
          perfil={perfil}
          onTrocarPerfil={onTrocarPerfil}
          coverUrl={coverUrl}
        />
      ) : (
        <div className="flex flex-col gap-6 xl:min-h-0 xl:shrink">
          <Composicao
            style={style}
            layout={layout}
            mode={mode}
            perfil={perfil}
            onTrocarPerfil={onTrocarPerfil}
            coverUrl={coverUrl}
          />
          <Trio />
        </div>
      )}
      <UltimosProjetos />
    </div>
  );
}
