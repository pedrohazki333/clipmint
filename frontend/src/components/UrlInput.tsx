"use client";

import { useState } from "react";
import type { ClipMode, LayoutMode, ManualMode, SourceType, SubtitleMode } from "@/lib/types";
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
}

/** O layout escolhido é o melhor palpite do tipo de conteúdo. */
function inferSourceType(layout: LayoutMode): SourceType {
  return layout === "streamer" ? "gameplay" : "podcast";
}

export default function UrlInput({
  onSubmit,
  isLoading,
  lockedSource,
  defaultLayout = "cover",
}: Props) {
  const [url, setUrl] = useState("");
  const [subtitleMode, setSubtitleMode] = useState<SubtitleMode>("word_highlight");
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
    if (!lockedSource && !sourceTouched) setSourceType(inferSourceType(mode));
  }

  function handleSourceChange(type: SourceType) {
    setSourceType(type);
    setSourceTouched(true);
  }

  function isValidYouTubeUrl(u: string): boolean {
    return /(?:youtube\.com\/watch\?v=|youtu\.be\/)/.test(u);
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError("");

    if (!url.trim()) {
      setError("Cole uma URL do YouTube.");
      return;
    }
    if (!isValidYouTubeUrl(url)) {
      setError("URL inválida. Use um link do YouTube (youtube.com/watch?v= ou youtu.be/).");
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
        <label htmlFor="url" className="text-sm font-medium text-gray-400">
          URL do YouTube
        </label>
        <input
          id="url"
          type="text"
          value={url}
          onChange={(e) => setUrl(e.target.value)}
          placeholder="https://www.youtube.com/watch?v=..."
          disabled={isLoading}
          className="w-full rounded-lg bg-gray-800 border border-gray-700 px-4 py-3 text-gray-100 placeholder-gray-500 focus:outline-none focus:border-emerald-500 disabled:opacity-50"
        />
        {error && <p className="text-sm text-red-400">{error}</p>}
      </div>

      <LayoutModeSelector value={layoutMode} onChange={handleLayoutChange} />

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
        className="w-full rounded-lg bg-emerald-500 hover:bg-emerald-400 disabled:bg-gray-700 disabled:cursor-not-allowed px-6 py-3 font-semibold text-white transition-colors"
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
