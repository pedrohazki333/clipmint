"use client";

import { useState } from "react";
import type { ClipMode, LayoutMode, ManualMode, SourceType, SubtitleMode } from "@/lib/types";
import { INVALID_YOUTUBE_URL_MESSAGE, isValidYouTubeUrl } from "@/lib/youtube";
import SubtitleModeSelector from "./SubtitleModeSelector";
import LayoutModeSelector from "./LayoutModeSelector";
import SourceTypeSelector from "./SourceTypeSelector";
import ClipModeSelector from "./ClipModeSelector";
import ManualClipsField from "./ManualClipsField";

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
}

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

export default function UrlInput({
  onSubmit,
  isLoading,
  lockedSource,
  defaultLayout = "cover",
  defaultSubtitle,
}: Props) {
  const [url, setUrl] = useState("");
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

  return (
    <form onSubmit={handleSubmit} className="flex flex-col gap-4">
      <div className="flex flex-col gap-2">
        <label htmlFor="url" className="text-body font-medium text-ink-dim">
          URL do YouTube
        </label>
        <input
          id="url"
          type="text"
          value={url}
          onChange={(e) => setUrl(e.target.value)}
          placeholder="https://www.youtube.com/watch?v=..."
          disabled={isLoading}
          className="w-full rounded-sm bg-inset border border-line px-4 py-3 text-ink placeholder-ink-muted focus:outline-none focus:border-mint disabled:opacity-50"
        />
        {error && <p className="text-body text-danger">{error}</p>}
      </div>

      <LayoutModeSelector
          value={layoutMode}
          onChange={handleLayoutChange}
          source={sourceType}
        />

      {!lockedSource && (
        <SourceTypeSelector
          value={sourceType}
          onChange={handleSourceChange}
          isInferred={!sourceTouched}
        />
      )}

      <ClipModeSelector value={clipMode} onChange={setClipMode} />

      <ManualClipsField
        value={manualClips}
        onChange={setManualClips}
        mode={manualMode}
        onModeChange={setManualMode}
        isCompilation={clipMode === "compilation"}
      />

      <SubtitleModeSelector value={subtitleMode} onChange={setSubtitleMode} />

      <button
        type="submit"
        disabled={isLoading}
        className="w-full rounded-sm bg-mint-strong hover:bg-mint disabled:bg-inset disabled:cursor-not-allowed px-6 py-3 font-semibold text-white transition-colors"
      >
        {isLoading
          ? "Processando..."
          : clipMode === "compilation"
            ? "Gerar Compilado"
            : "Gerar Clips"}
      </button>
    </form>
  );
}
