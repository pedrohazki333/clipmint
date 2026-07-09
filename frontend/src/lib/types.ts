export type SubtitleMode = "word_highlight" | "traditional" | "none";

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
}
