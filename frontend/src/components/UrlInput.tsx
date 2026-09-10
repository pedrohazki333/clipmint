"use client";

import { useState } from "react";

import type { ClipMode, LayoutMode, ManualMode, SourceType, SubtitleMode } from "@/lib/types";
import { INVALID_YOUTUBE_URL_MESSAGE, isValidYouTubeUrl } from "@/lib/youtube";
import { LAYOUT_LABELS } from "@/lib/layouts";
import { PUBLIC_NICHES } from "@/lib/features";
import { PERSONAL_NICHES } from "@/personal";
import { Button, Input, SectionCard } from "@/components/ui";
import { SectionIcon } from "@/lib/section-icons";
import SubtitleModeSelector, { SUBTITLE_LABELS } from "./SubtitleModeSelector";
import LayoutModeSelector from "./LayoutModeSelector";
import SourceTypeSelector from "./SourceTypeSelector";
import ClipModeSelector, { CLIP_MODE_LABELS } from "./ClipModeSelector";
import ManualClipsField from "./ManualClipsField";

const NICHES = [...PUBLIC_NICHES, ...PERSONAL_NICHES];

interface Props {
  onSubmit: (
    url: string,
    subtitleMode: SubtitleMode,
    layoutMode: LayoutMode,
    sourceType: SourceType,
    clipMode: ClipMode,
    manualClips: string,
    manualMode: ManualMode,
  ) => Promise<void>;
  isLoading: boolean;
  /** Fixa o nicho (páginas de conta): o seletor some e o valor não muda. */
  lockedSource?: SourceType;
  /** Layout inicial sugerido pela página. */
  defaultLayout?: LayoutMode;
  /** Modo de legenda com que o formulário abre. Vem do perfil; segue editável. */
  defaultSubtitle?: SubtitleMode;
  /**
   * URL com que o campo abre. Vem do link colado no hero da landing, que
   * atravessa o cadastro e a criação do perfil — ver HeroUrlForm.
   */
  defaultUrl?: string;
}

/**
 * O pedido de geração: o link, os trechos e — recolhidos — os ajustes.
 *
 * ── Por que o botão subiu ────────────────────────────────────────────────────
 * O formulário mostrava cinco blocos de configuração antes do botão de gerar, e
 * os quatro primeiros já vinham respondidos pelo perfil. Quem chegava pela
 * primeira vez colava o link e encontrava, no lugar do botão, uma fila de
 * escolhas que já estavam feitas — e o botão a uma rolagem de distância. Agora
 * link e botão dividem a mesma linha: dá para colar e gerar sem descer a tela.
 *
 * ── Por que os ajustes viraram um resumo ─────────────────────────────────────
 * Nenhum controle saiu; eles ficam atrás de uma linha que DIZ o que vai ser
 * usado ("Capa + banner · Palavra a palavra · Clipes individuais"). Recolher
 * sem mostrar o valor teria trocado repetição por mistério, e a pergunta que a
 * pessoa faz aqui não é "quais são as opções", é "vai sair como da última vez?".
 * A resposta cabe numa linha; mudar continua a um clique.
 */

/**
 * O palpite de rubrica a partir do layout — só onde ele existe.
 *
 * `cover` e `streamer` presumem o tipo de conteúdo, então dizem algo sobre a
 * rubrica. `crop` e `original` não presumem nada: escolher um deles não é razão
 * para trocar a rubrica, e por isso devolvem `null`.
 *
 * Desde os perfis, a direção normal é a inversa (a rubrica decide os layouts).
 * Isto só age quando não há perfil travando o nicho.
 */
function inferSourceType(layout: LayoutMode): SourceType | null {
  if (layout === "streamer") return "gameplay";
  if (layout === "cover") return "podcast";
  return null;
}

function Chevron({ aberto }: { aberto: boolean }) {
  return (
    <svg
      viewBox="0 0 24 24"
      className={`h-4 w-4 transition-transform ${aberto ? "rotate-180" : ""}`}
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      <path d="m6 9 6 6 6-6" />
    </svg>
  );
}

export default function UrlInput({
  onSubmit,
  isLoading,
  lockedSource,
  defaultLayout = "cover",
  defaultSubtitle,
  defaultUrl,
}: Props) {
  const [url, setUrl] = useState(defaultUrl ?? "");
  const [subtitleMode, setSubtitleMode] = useState<SubtitleMode>(
    defaultSubtitle ?? "word_highlight",
  );
  const [layoutMode, setLayoutMode] = useState<LayoutMode>(defaultLayout);
  const [sourceType, setSourceType] = useState<SourceType>(lockedSource ?? "podcast");
  // Enquanto o usuário não escolher à mão, o tipo acompanha o layout.
  const [sourceTouched, setSourceTouched] = useState(false);
  const [clipMode, setClipMode] = useState<ClipMode>("individual");
  const [manualClips, setManualClips] = useState("");
  const [manualMode, setManualMode] = useState<ManualMode>("only");
  const [error, setError] = useState("");
  const [ajustesAbertos, setAjustesAbertos] = useState(false);

  function handleLayoutChange(mode: LayoutMode) {
    setLayoutMode(mode);
    // Com o nicho travado pela página, o layout não pode arrastá-lo junto.
    if (!lockedSource && !sourceTouched) {
      const palpite = inferSourceType(mode);
      if (palpite) setSourceType(palpite);
    }
  }

  function handleSourceChange(type: SourceType) {
    setSourceType(type);
    setSourceTouched(true);
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError("");

    if (!url.trim()) {
      setError("Cole uma URL do YouTube.");
      return;
    }
    if (!isValidYouTubeUrl(url)) {
      setError(INVALID_YOUTUBE_URL_MESSAGE);
      return;
    }

    await onSubmit(
      url.trim(),
      subtitleMode,
      layoutMode,
      sourceType,
      clipMode,
      manualClips,
      manualMode,
    );
    setUrl("");
  }

  /** O que vai ser usado, em uma linha — o conteúdo do resumo fechado. */
  const resumo = [
    LAYOUT_LABELS[layoutMode].nome,
    SUBTITLE_LABELS[subtitleMode],
    CLIP_MODE_LABELS[clipMode],
    lockedSource ? null : NICHES.find((n) => n.source === sourceType)?.title,
  ]
    .filter(Boolean)
    .join(" · ");

  return (
    <form onSubmit={handleSubmit} className="flex flex-col gap-4">
      {/* ── O vídeo: link, botão e trechos ───────────────────────────────── */}
      <div className="flex flex-col gap-5 rounded-md border border-line bg-raised p-4 sm:p-5">
        <div className="flex flex-col gap-2">
          <label htmlFor="url" className="text-body font-medium text-ink">
            Link do vídeo no YouTube
          </label>
          {/* No celular o botão passa para baixo e ocupa a largura toda: lado a
              lado, sobrariam uns 60px para o campo de link. */}
          <div className="flex flex-col gap-2 sm:flex-row">
            <Input
              id="url"
              type="text"
              value={url}
              onChange={(e) => setUrl(e.target.value)}
              placeholder="https://www.youtube.com/watch?v=..."
              disabled={isLoading}
              className="sm:flex-1"
            />
            <Button type="submit" disabled={isLoading} className="sm:flex-shrink-0">
              {isLoading
                ? "Processando..."
                : clipMode === "compilation"
                  ? "Gerar compilado"
                  : "Gerar clipes"}
            </Button>
          </div>
          {error && <p className="text-body text-danger">{error}</p>}
        </div>

        <ManualClipsField
          value={manualClips}
          onChange={setManualClips}
          mode={manualMode}
          onModeChange={setManualMode}
          isCompilation={clipMode === "compilation"}
          disabled={isLoading}
        />
      </div>

      {/* ── Ajustes deste vídeo ──────────────────────────────────────────── */}
      <div className="flex flex-col gap-3">
        <button
          type="button"
          onClick={() => setAjustesAbertos((v) => !v)}
          aria-expanded={ajustesAbertos}
          className="flex items-center gap-3 rounded-md border border-line bg-raised p-4 text-left transition-colors hover:border-line-strong"
        >
          <span className="flex h-9 w-9 flex-shrink-0 items-center justify-center rounded-sm border border-line bg-inset text-mint">
            <SectionIcon name="ajustes" />
          </span>
          <span className="min-w-0 flex-1">
            <span className="block text-body font-medium text-ink">
              Ajustes deste vídeo
            </span>
            <span className="mt-0.5 block truncate text-label text-ink-muted">
              {resumo}
            </span>
          </span>
          <span className="flex flex-shrink-0 items-center gap-1.5 text-label text-ink-dim">
            <span className="hidden sm:inline">
              {ajustesAbertos ? "Fechar" : "Ajustar"}
            </span>
            <Chevron aberto={ajustesAbertos} />
          </span>
        </button>

        {ajustesAbertos && (
          <>
            <p className="text-label leading-relaxed text-ink-muted">
              Vêm do perfil e valem só para este vídeo — o perfil continua como
              está.
            </p>

            <SectionCard
              icon="layout"
              title="Layout do clipe"
              description="Como o vertical é montado."
            >
              <LayoutModeSelector
                value={layoutMode}
                onChange={handleLayoutChange}
                source={sourceType}
              />
            </SectionCard>

            <SectionCard
              icon="legenda"
              title="Legenda"
              description="Como a fala aparece na tela de quem assiste sem som."
            >
              <SubtitleModeSelector value={subtitleMode} onChange={setSubtitleMode} />
            </SectionCard>

            <SectionCard
              icon="formato"
              title="Formato"
              description="Um clipe por momento, ou os momentos emendados num vídeo só."
            >
              <ClipModeSelector value={clipMode} onChange={setClipMode} />
            </SectionCard>

            {!lockedSource && (
              <SectionCard
                icon="identidade"
                title="Tipo de conteúdo"
                description="A rubrica que dá nota aos trechos deste vídeo."
              >
                <SourceTypeSelector
                  value={sourceType}
                  onChange={handleSourceChange}
                  isInferred={!sourceTouched}
                />
              </SectionCard>
            )}
          </>
        )}
      </div>
    </form>
  );
}
