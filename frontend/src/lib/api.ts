import axios from "axios";
import type {
  Job,
  JobDetail,
  Clip,
  CreateJobPayload,
  Reference,
  SourceType,
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

/** Sem `source`, traz as duas contas; com ele, só a do nicho pedido. */
export async function listJobs(source?: SourceType): Promise<Job[]> {
  const { data } = await api.get<Job[]>("/jobs", {
    params: source ? { source } : undefined,
  });
  return data;
}

export async function getJob(jobId: string): Promise<JobDetail> {
  const { data } = await api.get<JobDetail>(`/jobs/${jobId}`);
  return data;
}

export async function deleteJob(jobId: string): Promise<void> {
  await api.delete(`/jobs/${jobId}`);
}

/**
 * Retoma um job interrompido/falho reaproveitando download, transcrição,
 * análise e clips já renderizados — só o que falta é refeito.
 */
export async function retryJob(jobId: string): Promise<Job> {
  const { data } = await api.post<Job>(`/jobs/${jobId}/retry`);
  return data;
}

export async function getClip(clipId: string): Promise<Clip> {
  const { data } = await api.get<Clip>(`/clips/${clipId}`);
  return data;
}

export function getDownloadUrl(clipId: string): string {
  return `/api/clips/${clipId}/download`;
}

export async function uploadWatermark(source: SourceType, file: File): Promise<void> {
  const form = new FormData();
  form.append("file", file);
  await api.post("/settings/watermark", form, {
    params: { source },
    headers: { "Content-Type": "multipart/form-data" },
  });
}

export async function deleteWatermark(source: SourceType): Promise<void> {
  await api.delete("/settings/watermark", { params: { source } });
}

export async function hasWatermark(source: SourceType): Promise<boolean> {
  try {
    await api.get("/settings/watermark", { params: { source }, responseType: "blob" });
    return true;
  } catch {
    return false;
  }
}

export function getWatermarkUrl(source: SourceType): string {
  return `/api/settings/watermark?source=${source}`;
}

export interface BannerColors {
  bg_color: string;
  text_color: string;
  customized: boolean;
}

export async function getBannerColors(source: SourceType): Promise<BannerColors> {
  const { data } = await api.get<BannerColors>("/settings/banner-colors", {
    params: { source },
  });
  return data;
}

export async function saveBannerColors(
  source: SourceType,
  bg_color: string,
  text_color: string
): Promise<BannerColors> {
  const { data } = await api.put<BannerColors>(
    "/settings/banner-colors",
    { bg_color, text_color },
    { params: { source } }
  );
  return data;
}

export async function resetBannerColors(source: SourceType): Promise<void> {
  await api.delete("/settings/banner-colors", { params: { source } });
}

/** Faixa divisória do modo streamer (onde o nome do streamer se repete). */
export interface BarStyle {
  bg_color: string;
  text_color: string;
  font: string;
  customized: boolean;
  /** Famílias instaladas na máquina do backend — a lista vem de lá. */
  available_fonts: { key: string; label: string }[];
}

export async function getBarStyle(source: SourceType): Promise<BarStyle> {
  const { data } = await api.get<BarStyle>("/settings/bar-style", {
    params: { source },
  });
  return data;
}

export async function saveBarStyle(
  source: SourceType,
  bg_color: string,
  text_color: string,
  font: string
): Promise<BarStyle> {
  const { data } = await api.put<BarStyle>(
    "/settings/bar-style",
    { bg_color, text_color, font },
    { params: { source } }
  );
  return data;
}

export async function resetBarStyle(source: SourceType): Promise<void> {
  await api.delete("/settings/bar-style", { params: { source } });
}

// ─── Cronograma de postagem ──────────────────────────────────────────────────

export interface ScheduleSlot {
  time: string;
  source_type: SourceType;
  axis: string;
}

export interface SchedulePick {
  clip_id: string;
  job_id: string;
  axis: string;
  axis_score: number | null;
  virality_score: number;
  source_type: SourceType;
  video_title: string | null;
  channel_name: string | null;
  start_time: number;
  end_time: number;
  duration: number;
  hook: string | null;
  suggested_title: string | null;
  verdict: string | null;
  file_path: string | null;
}

export async function listScheduleSlots(): Promise<ScheduleSlot[]> {
  const { data } = await api.get<ScheduleSlot[]>("/schedule/slots");
  return data;
}

export async function pickForSlot(
  axis: string,
  source: SourceType,
  exclude: string[] = []
): Promise<SchedulePick[]> {
  const { data } = await api.get<SchedulePick[]>("/schedule/pick", {
    params: { axis, source, limit: 1, exclude: exclude.join(",") || undefined },
  });
  return data;
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
