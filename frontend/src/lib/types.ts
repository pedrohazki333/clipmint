export type SubtitleMode = "word_highlight" | "traditional" | "none";

export type LayoutMode = "cover" | "streamer";

/** Caixa da facecam em frações (0–1) da fonte. */
export interface FacecamRect {
  x: number;
  y: number;
  w: number;
  h: number;
  confidence?: number;
  method?: string;
}

export type JobStatus =
  | "queued"
  | "downloading"
  | "transcribing"
  | "analyzing"
  | "clipping"
  | "done"
  | "error";

export type ClipStatus = "processing" | "ready" | "error";

export interface Job {
  id: string;
  youtube_url: string;
  video_title: string | null;
  channel_name: string | null;
  duration_seconds: number | null;
  thumbnail_url: string | null;
  subtitle_mode: SubtitleMode;
  layout_mode: LayoutMode;
  facecam_rect: FacecamRect | null;
  status: JobStatus;
  error_message: string | null;
  created_at: string;
  updated_at: string;
}

export interface Clip {
  id: string;
  job_id: string;
  start_time: number;
  end_time: number;
  duration: number;
  virality_score: number;
  hook: string | null;
  reason: string | null;
  tags_json: string | null;
  suggested_title: string | null;
  transcript_excerpt: string | null;
  part_number: number | null;
  parent_clip_id: string | null;
  subtitle_mode: SubtitleMode;
  status: ClipStatus;
  file_path: string | null;
  file_size_bytes: number | null;
  created_at: string;
}

export interface JobDetail extends Job {
  clips: Clip[];
}

export interface CreateJobPayload {
  youtube_url: string;
  subtitle_mode: SubtitleMode;
  layout_mode?: LayoutMode;
  /** Só no modo streamer; omitido = detecção automática da webcam. */
  facecam_rect?: FacecamRect;
}

// ─── Referências (aprender com clipe viral de outro criador) ──────────────────

export type ReferenceStatus =
  | "queued"
  | "downloading_source"
  | "transcribing"
  | "aligning"
  | "analyzing"
  | "done"
  | "error";

export type Performance = "viral" | "muito_bom" | "bom";

export interface ReferenceAnalysis {
  hook: string;
  suggested_title: string;
  virality_score: number;
  reason: string;
  tags: string[];
  why_this_cut: string;
}

export interface Reference {
  id: string;
  source_url: string;
  source_title: string | null;
  source_channel: string | null;
  source_duration: number | null;
  language: string | null;
  source_start: number | null;
  source_end: number | null;
  alignment_confidence: number | null;
  clip_duration: number | null;
  analysis: ReferenceAnalysis | null;
  opening_phrase: string | null;
  transcript_excerpt: string | null;
  performance: Performance | null;
  views: number | null;
  notas: string | null;
  status: ReferenceStatus;
  error_message: string | null;
  published: boolean;
  example_path: string | null;
  created_at: string;
  updated_at: string;
}

export interface UpdateReferencePayload {
  source_start?: number;
  source_end?: number;
  performance?: Performance;
  views?: number;
  notas?: string;
  reanalyze?: boolean;
}

// ─── Padrões aprendidos (Fase 3) ──────────────────────────────────────────────

export interface LearnedPatterns {
  patterns: string[];
  patterns_text: string;
  generated_at: string | null;
  n_examples: number;
  available_examples: number;
  stats: Record<string, unknown> | null;
  stale: boolean;
}
