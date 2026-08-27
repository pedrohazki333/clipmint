/**
 * Cliente das rotas de aprendizado — só existem na versão pessoal.
 *
 * Aprender com clipe viral de outro criador, os padrões minerados deles e a
 * validação de um clipe próprio como exemplo. As três alimentam
 * `prompt_engine/examples/validated/`, uma pasta ÚNICA que o PromptBuilder
 * injeta na análise de todo mundo — no build público isso faria o aprendizado
 * de um usuário mudar o corte dos outros.
 *
 * Ficam fora de `lib/api.ts` pelo mesmo motivo do Melhorar vídeo: lá entrariam
 * no grafo de módulos do build público e as URLs poderiam sobreviver no bundle
 * como código morto.
 */

import { api } from "@/lib/api";

import type {
  LearnedPatterns,
  Reference,
  SourceType,
  UpdateReferencePayload,
} from "@/lib/types";

export async function createReference(
  sourceUrl: string,
  clip: File,
  sourceType: SourceType = "podcast"
): Promise<Reference> {
  const form = new FormData();
  form.append("source_url", sourceUrl);
  form.append("clip", clip);
  form.append("source_type", sourceType);
  const { data } = await api.post<Reference>("/references", form, {
    headers: { "Content-Type": "multipart/form-data" },
  });
  return data;
}

/**
 * Aprende com um clipe viral sem ter o vídeo de origem (o caso do TikTok).
 *
 * Só o arquivo é obrigatório: o resto é contexto que entra na análise quando o
 * usuário souber. Exigir qualquer outra coisa anularia o motivo deste caminho
 * existir.
 */
export async function createStandaloneReference(payload: {
  clip: File;
  title?: string;
  channel?: string;
  postUrl?: string;
  sourceType?: SourceType;
  notas?: string;
}): Promise<Reference> {
  const form = new FormData();
  form.append("clip", payload.clip);
  form.append("title", payload.title ?? "");
  form.append("channel", payload.channel ?? "");
  form.append("post_url", payload.postUrl ?? "");
  form.append("source_type", payload.sourceType ?? "podcast");
  form.append("notas", payload.notas ?? "");
  const { data } = await api.post<Reference>("/references/standalone", form, {
    headers: { "Content-Type": "multipart/form-data" },
  });
  return data;
}

export async function listReferences(): Promise<Reference[]> {
  const { data } = await api.get<Reference[]>("/references");
  return data;
}

export async function getReference(id: string): Promise<Reference> {
  const { data } = await api.get<Reference>(`/references/${id}`);
  return data;
}

export async function updateReference(
  id: string,
  payload: UpdateReferencePayload
): Promise<Reference> {
  const { data } = await api.patch<Reference>(`/references/${id}`, payload);
  return data;
}

export async function confirmReference(
  id: string
): Promise<{ reference_id: string; example_path: string }> {
  const { data } = await api.post(`/references/${id}/confirm`);
  return data;
}

export async function deleteReference(id: string): Promise<void> {
  await api.delete(`/references/${id}`);
}

// ─── Padrões aprendidos (Fase 3) ──────────────────────────────────────────────

export async function getPatterns(): Promise<LearnedPatterns> {
  const { data } = await api.get<LearnedPatterns>("/patterns");
  return data;
}

export async function minePatterns(): Promise<LearnedPatterns> {
  const { data } = await api.post<LearnedPatterns>("/patterns/mine");
  return data;
}

export async function deletePatterns(): Promise<void> {
  await api.delete("/patterns");
}

export async function validateClip(
  clipId: string,
  payload: { performance: "viral" | "muito_bom" | "bom"; aprendizado: string; views?: number }
): Promise<{ clip_id: string; example_path: string }> {
  const { data } = await api.post(`/clips/${clipId}/validate`, payload);
  return data;
}
