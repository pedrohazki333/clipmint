import axios from "axios";
import type { Job, JobDetail, Clip, CreateJobPayload } from "./types";

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

export async function validateClip(
  clipId: string,
  payload: { performance: "viral" | "muito_bom" | "bom"; aprendizado: string; views?: number }
): Promise<{ clip_id: string; example_path: string }> {
  const { data } = await api.post(`/clips/${clipId}/validate`, payload);
  return data;
}
