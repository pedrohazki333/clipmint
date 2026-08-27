/**
 * Cliente da API da aba Melhorar vídeo — só existe na versão pessoal.
 *
 * Estas funções ficam fora de lib/api.ts de propósito: lá elas entrariam no
 * grafo de módulos do build público e as URLs de /api/video-enhance poderiam
 * sobreviver no bundle como código morto. Aqui, nada importa este arquivo no
 * build público (ver src/lib/features.ts).
 */

import { api } from "@/lib/api";

import type { VideoEnhanceJob } from "./types";

export async function createVideoEnhance(video: File): Promise<VideoEnhanceJob> {
  const form = new FormData();
  form.append("video", video);
  const { data } = await api.post<VideoEnhanceJob>("/video-enhance", form, {
    headers: { "Content-Type": "multipart/form-data" },
  });
  return data;
}

export async function listVideoEnhance(): Promise<VideoEnhanceJob[]> {
  const { data } = await api.get<VideoEnhanceJob[]>("/video-enhance");
  return data;
}

export async function deleteVideoEnhance(id: string): Promise<void> {
  await api.delete(`/video-enhance/${id}`);
}

/** Inline, para o <video>. O /download manda attachment e o player não tocaria. */
export function getVideoEnhanceStreamUrl(id: string): string {
  return `/api/video-enhance/${id}/video`;
}

export function getVideoEnhanceDownloadUrl(id: string): string {
  return `/api/video-enhance/${id}/download`;
}
