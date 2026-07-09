"use client";

import { useState } from "react";
import type { SubtitleMode } from "@/lib/types";
import SubtitleModeSelector from "./SubtitleModeSelector";

interface Props {
  onSubmit: (url: string, subtitleMode: SubtitleMode) => Promise<void>;
  isLoading: boolean;
}

export default function UrlInput({ onSubmit, isLoading }: Props) {
  const [url, setUrl] = useState("");
  const [subtitleMode, setSubtitleMode] = useState<SubtitleMode>("word_highlight");
  const [error, setError] = useState("");

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

    await onSubmit(url.trim(), subtitleMode);
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

      <SubtitleModeSelector value={subtitleMode} onChange={setSubtitleMode} />

      <button
        type="submit"
        disabled={isLoading}
        className="w-full rounded-lg bg-emerald-500 hover:bg-emerald-400 disabled:bg-gray-700 disabled:cursor-not-allowed px-6 py-3 font-semibold text-white transition-colors"
      >
        {isLoading ? "Processando..." : "Gerar Clips"}
      </button>
    </form>
  );
}
