export type SubtitleMode = "word_highlight" | "traditional" | "none";

export type LayoutMode = "cover" | "streamer";

/** Muda a rubrica da análise e define a conta no cronograma de postagem. */
export type SourceType = "podcast" | "gameplay" | "siege";

/**
 * "compilation" PEDE um compilado (vários momentos costurados num vídeo só).
 * Não achando material que se sustente, o backend entrega clipes individuais.
 */
export type ClipMode = "individual" | "compilation";

/**
 * O que fazer com os trechos que o usuário indicou à mão.
 * "only" corta apenas eles; "plus" mantém a análise procurando outros além.
 */
export type ManualMode = "only" | "plus";

/** Eixos da rubrica de viralidade, 0–10 cada. */
export const SCORE_AXES = [
  { key: "hook_score", label: "Gancho", hint: "Força nos 3 primeiros segundos" },
  { key: "retention_score", label: "Retenção", hint: "Segura a atenção até o fim" },
  { key: "shareability_score", label: "Compart.", hint: "Eu mandaria isso pra alguém" },
  { key: "comment_bait_score", label: "Comentários", hint: "Gera debate ou reação" },
  { key: "loopability_score", label: "Loop", hint: "O fim reconecta com o início" },
] as const;

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
  source_type: SourceType;
  clip_mode: ClipMode;
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
  /** Nulos em clipes analisados antes da rubrica de cinco eixos. */
  hook_score: number | null;
  retention_score: number | null;
  shareability_score: number | null;
  loopability_score: number | null;
  comment_bait_score: number | null;
  verdict: string | null;
  weak_points_json: string | null;
  trim_reason: string | null;
  /** JSON [[ini,fim],...] quando o clipe foi costurado de vários trechos. */
  segments_json: string | null;
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
  /** Omitido = inferido do layout (streamer→gameplay, cover→podcast). */
  source_type?: SourceType;
  /** Omitido = "individual" (um clipe por momento, como sempre). */
  clip_mode?: ClipMode;
  /** Trechos indicados à mão, como digitados ("3:24 - 4:10, 12:05 - 12:40"). */
  manual_clips?: string;
  /** Só faz sentido junto de manual_clips. Omitido = "only". */
  manual_mode?: ManualMode;
  /** Só no modo streamer; omitido = detecção automática da webcam. */
  facecam_rect?: FacecamRect;
}

// ─── Referências (aprender com clipe viral de outro criador) ──────────────────

/**
 * Como a referência foi aprendida.
 *
 * "aligned"    — veio com a URL do vídeo original e o corte foi localizado
 *                dentro dele. Sabe o que ficou de fora.
 * "standalone" — só o arquivo do clipe (o caso do TikTok). O clipe é periciado
 *                por si: fala, som, imagem e cortes.
 */
export type ReferenceKind = "aligned" | "standalone";

export type ReferenceStatus =
  | "queued"
  // modo alinhado
  | "downloading_source"
  | "aligning"
  // modo standalone
  | "extracting"
  | "watching"
  // comuns aos dois
  | "transcribing"
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

export interface ClipBeat {
  start: number;
  end: number;
  role: string;
  what: string;
}

export interface ClipHookBreakdown {
  first_frame?: string | null;
  first_line?: string | null;
  on_screen_text?: string | null;
  mechanism?: string | null;
  seconds_to_promise?: number | null;
}

/** A perícia detalhada de um clipe standalone (backend: forensics_json). */
export interface ClipForensics {
  hook_breakdown?: ClipHookBreakdown | null;
  beats?: ClipBeat[] | null;
  audio_role?: string | null;
  visual_style?: string | null;
  text_strategy?: string | null;
  edit_rhythm?: string | null;
  retention_devices?: string[] | null;
  share_trigger?: string | null;
  comment_bait?: string | null;
  ending?: string | null;
  /** Regras de escolha de corte — o que entra no prompt do analisador. */
  transferable_rules?: string[] | null;
  /** Lições de montagem: verdadeiras sobre o clipe, mas fora do alcance de quem só corta. */
  production_notes?: string[] | null;
  do_not_copy?: string[] | null;
  evidence_gaps?: string[] | null;
}

export interface Reference {
  id: string;
  kind: ReferenceKind;
  source_type: SourceType;
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
  /** Só no modo standalone. */
  forensics: ClipForensics | null;
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

// ─── Melhorar vídeo ──────────────────────────────────────────────────────────

export type VideoEnhanceStatus = "pending" | "processing" | "done" | "failed";

export interface VideoEnhanceJob {
  id: string;
  original_filename: string | null;
  status: VideoEnhanceStatus;
  /** Etapa atual ("fazendo upscale"). Só vem durante o trabalho. */
  status_detail: string | null;
  /**
   * Em `failed`, o motivo. Em `done`, o aviso das etapas que falharam — o vídeo
   * existe do mesmo jeito.
   */
  error_message: string | null;
  /** Antes/depois em texto, ex.: "720x1280 · 24fps · 1.9 Mbps". */
  source_summary: string | null;
  final_summary: string | null;
  steps_applied: string[];
  /** Dispensadas por já estarem no alvo — não são problema. */
  steps_skipped: string[];
  has_video: boolean;
  created_at: string;
  updated_at: string;
}
