import axios from "axios";
import type {
  Job,
  JobDetail,
  Clip,
  CreateJobPayload,
  Reference,
  UpdateReferencePayload,
  LearnedPatterns,
} from "./types";

/** Extrai uma mensagem legível de um erro de API (detail do FastAPI ou fallback). */
export function getApiErrorMessage(err: unknown, fallback: string): string {
  if (axios.isAxiosError(err)) {
    const detail = err.response?.data?.detail;
    if (typeof detail === "string") return detail;
    // Erros de validação do FastAPI vêm como lista de {msg, loc, ...}
    if (Array.isArray(detail) && detail[0]?.msg) return detail[0].msg;
  }
  return fallback;
}

const api = axios.create({
  baseURL: "/api",
  headers: { "Content-Type": "application/json" },
});

export async function createJob(payload: CreateJobPayload): Promise<Job> {
  const { data } = await api.post<Job>("/jobs", payload);
  return data;
}

export async function listJobs(): Promise<Job[]> {
  const { data } = await api.get<Job[]>("/jobs");
  return data;
}

export async function getJob(jobId: string): Promise<JobDetail> {
  const { data } = await api.get<JobDetail>(`/jobs/${jobId}`);
  return data;
}

export async function deleteJob(jobId: string): Promise<void> {
  await api.delete(`/jobs/${jobId}`);
}

export async function getClip(clipId: string): Promise<Clip> {
  const { data } = await api.get<Clip>(`/clips/${clipId}`);
  return data;
}

export function getDownloadUrl(clipId: string): string {
  return `/api/clips/${clipId}/download`;
}

export async function uploadWatermark(file: File): Promise<void> {
  const form = new FormData();
  form.append("file", file);
  await api.post("/settings/watermark", form, {
    headers: { "Content-Type": "multipart/form-data" },
  });
}

export async function deleteWatermark(): Promise<void> {
  await api.delete("/settings/watermark");
}

export async function hasWatermark(): Promise<boolean> {
  try {
    await api.get("/settings/watermark", { responseType: "blob" });
    return true;
  } catch {
    return false;
  }
}

export function getWatermarkUrl(): string {
  return "/api/settings/watermark";
}

export interface BannerColors {
  bg_color: string;
  text_color: string;
  customized: boolean;
}

export async function getBannerColors(): Promise<BannerColors> {
  const { data } = await api.get<BannerColors>("/settings/banner-colors");
  return data;
}

export async function saveBannerColors(
  bg_color: string,
  text_color: string
): Promise<BannerColors> {
  const { data } = await api.put<BannerColors>("/settings/banner-colors", {
    bg_color,
    text_color,
  });
  return data;
}

export async function resetBannerColors(): Promise<void> {
  await api.delete("/settings/banner-colors");
}

export async function validateClip(
  clipId: string,
  payload: { performance: "viral" | "muito_bom" | "bom"; aprendizado: string; views?: number }
): Promise<{ clip_id: string; example_path: string }> {
  const { data } = await api.post(`/clips/${clipId}/validate`, payload);
  return data;
}

// ─── Referências (aprender com clipe viral de outro criador) ──────────────────

export async function createReference(sourceUrl: string, clip: File): Promise<Reference> {
  const form = new FormData();
  form.append("source_url", sourceUrl);
  form.append("clip", clip);
  const { data } = await api.post<Reference>("/references", form, {
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
