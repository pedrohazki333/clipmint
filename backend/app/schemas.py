import re
from datetime import datetime
from typing import Optional, List, Literal
from pydantic import BaseModel, field_validator

_YOUTUBE_URL_RE = re.compile(
    r"^https?://(www\.|m\.)?(youtube\.com/(watch\?|shorts/|live/)|youtu\.be/)"
)


# ─── Job ───────────────────────────────────────────────────────────────────────

class JobCreate(BaseModel):
    youtube_url: str
    subtitle_mode: Literal["word_highlight", "traditional", "none"] = "word_highlight"

    @field_validator("youtube_url")
    @classmethod
    def validate_youtube_url(cls, v: str) -> str:
        v = v.strip()
        if not _YOUTUBE_URL_RE.match(v):
            raise ValueError("URL inválida: forneça um link do YouTube (youtube.com ou youtu.be)")
        return v


class JobResponse(BaseModel):
    id: str
    youtube_url: str
    video_title: Optional[str]
    channel_name: Optional[str]
    duration_seconds: Optional[float]
    thumbnail_url: Optional[str]
    subtitle_mode: str
    status: str
    error_message: Optional[str]
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


# ─── Clip ──────────────────────────────────────────────────────────────────────

class ClipResponse(BaseModel):
    id: str
    job_id: str
    start_time: float
    end_time: float
    duration: float
    virality_score: float
    hook: Optional[str]
    reason: Optional[str]
    tags_json: Optional[str]
    suggested_title: Optional[str]
    transcript_excerpt: Optional[str]
    part_number: Optional[int]
    parent_clip_id: Optional[str]
    subtitle_mode: str
    status: str
    file_path: Optional[str]
    file_size_bytes: Optional[int]
    created_at: datetime

    model_config = {"from_attributes": True}


# ─── Job Detail (com clips aninhados) ─────────────────────────────────────────

class JobDetailResponse(JobResponse):
    clips: List[ClipResponse] = []

    model_config = {"from_attributes": True}


# ─── Validação de exemplo (few-shot) ──────────────────────────────────────────

class ValidateClipRequest(BaseModel):
    performance: Literal["viral", "muito_bom", "bom"]
    aprendizado: str = ""
    views: Optional[int] = None


class ValidateClipResponse(BaseModel):
    example_path: str
    clip_id: str
