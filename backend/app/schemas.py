import json
import re
from datetime import datetime
from typing import Optional, List, Literal
from pydantic import BaseModel, Field, field_validator, model_validator

_YOUTUBE_URL_RE = re.compile(
    r"^https?://(www\.|m\.)?(youtube\.com/(watch\?|shorts/|live/)|youtu\.be/)"
)


# ─── Job ───────────────────────────────────────────────────────────────────────

class FacecamRectPayload(BaseModel):
    """Caixa da facecam em frações (0–1) da fonte."""

    x: float = Field(ge=0, lt=1)
    y: float = Field(ge=0, lt=1)
    w: float = Field(gt=0, le=1)
    h: float = Field(gt=0, le=1)

    @model_validator(mode="after")
    def validate_inside_frame(self) -> "FacecamRectPayload":
        if self.x + self.w > 1.0 or self.y + self.h > 1.0:
            raise ValueError("A caixa da facecam ultrapassa os limites do vídeo")
        return self


class JobCreate(BaseModel):
    youtube_url: str
    subtitle_mode: Literal["word_highlight", "traditional", "none"] = "word_highlight"
    layout_mode: Literal["cover", "streamer"] = "cover"
    # Só no modo streamer: posição da facecam. Omitido = detecção automática.
    facecam_rect: Optional[FacecamRectPayload] = None

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
    layout_mode: str = "cover"
    facecam_rect: Optional[dict] = None
    status: str
    error_message: Optional[str]
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}

    @field_validator("layout_mode", mode="before")
    @classmethod
    def default_layout_mode(cls, v: Optional[str]) -> str:
        # Jobs criados antes da coluna existir vêm sem valor
        return v or "cover"

    @field_validator("facecam_rect", mode="before")
    @classmethod
    def parse_facecam_rect(cls, v):
        """A coluna guarda JSON serializado; a API entrega o objeto."""
        if not isinstance(v, str):
            return v
        try:
            return json.loads(v)
        except json.JSONDecodeError:
            return None


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


# ─── Referência (aprender com clipe viral de outro criador) ───────────────────

class ReferenceResponse(BaseModel):
    id: str
    source_url: str
    source_title: Optional[str]
    source_channel: Optional[str]
    source_duration: Optional[float]
    language: Optional[str]
    source_start: Optional[float]
    source_end: Optional[float]
    alignment_confidence: Optional[float]
    clip_duration: Optional[float]
    analysis: Optional[dict] = None       # analysis_json parseado
    opening_phrase: Optional[str]
    transcript_excerpt: Optional[str]
    performance: Optional[str]
    views: Optional[int]
    notas: Optional[str]
    status: str
    error_message: Optional[str]
    published: bool
    example_path: Optional[str]
    created_at: datetime
    updated_at: datetime


class ReferenceUpdateRequest(BaseModel):
    """Ajustes do usuário sobre a referência analisada."""
    source_start: Optional[float] = None
    source_end: Optional[float] = None
    performance: Optional[Literal["viral", "muito_bom", "bom"]] = None
    views: Optional[int] = None
    notas: Optional[str] = None
    reanalyze: bool = False               # re-roda a análise reversa com o novo intervalo


class ReferenceConfirmResponse(BaseModel):
    reference_id: str
    example_path: str
