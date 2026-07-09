import axios from "axios";
import type { Job, JobDetail, Clip, CreateJobPayload } from "./types";

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

export async function validateClip(
  clipId: string,
  payload: { performance: "viral" | "muito_bom" | "bom"; aprendizado: string; views?: number }
): Promise<{ clip_id: string; example_path: string }> {
  const { data } = await api.post(`/clips/${clipId}/validate`, payload);
  return data;
}
