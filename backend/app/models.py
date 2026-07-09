from datetime import datetime, timezone
from uuid import uuid4
from sqlalchemy import Column, String, Float, Integer, Text, DateTime, ForeignKey
from sqlalchemy.orm import relationship

from app.database import Base


def uuid4_hex() -> str:
    return uuid4().hex


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Job(Base):
    __tablename__ = "jobs"

    id = Column(String, primary_key=True, default=uuid4_hex)
    youtube_url = Column(String, nullable=False)
    video_title = Column(String, nullable=True)
    channel_name = Column(String, nullable=True)
    duration_seconds = Column(Float, nullable=True)
    thumbnail_url = Column(String, nullable=True)
    video_path = Column(String, nullable=True)
    audio_path = Column(String, nullable=True)
    subtitle_mode = Column(String, default="word_highlight")  # word_highlight | traditional | none
    status = Column(String, default="queued")  # queued|downloading|transcribing|analyzing|clipping|done|error
    error_message = Column(String, nullable=True)
    created_at = Column(DateTime(timezone=True), default=utcnow)
    updated_at = Column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    transcript = relationship("Transcript", back_populates="job", uselist=False)
    clips = relationship("Clip", back_populates="job")


class Transcript(Base):
    __tablename__ = "transcripts"

    id = Column(String, primary_key=True, default=uuid4_hex)
    job_id = Column(String, ForeignKey("jobs.id"), nullable=False)
    full_text = Column(Text, nullable=False)
    words_json_path = Column(String, nullable=False)  # path pro JSON com word-level timestamps
    language = Column(String, nullable=True)
    confidence = Column(Float, nullable=True)
    created_at = Column(DateTime(timezone=True), default=utcnow)

    job = relationship("Job", back_populates="transcript")


class Clip(Base):
    __tablename__ = "clips"

    id = Column(String, primary_key=True, default=uuid4_hex)
    job_id = Column(String, ForeignKey("jobs.id"), nullable=False)
    start_time = Column(Float, nullable=False)
    end_time = Column(Float, nullable=False)
    duration = Column(Float, nullable=False)
    virality_score = Column(Float, nullable=False)
    hook = Column(String, nullable=True)
    reason = Column(String, nullable=True)
    tags_json = Column(String, nullable=True)       # JSON array de tags
    suggested_title = Column(String, nullable=True)
    transcript_excerpt = Column(Text, nullable=True)
    part_number = Column(Integer, nullable=True)    # 1, 2 (null se não dividido)
    parent_clip_id = Column(String, nullable=True)  # referência ao clip original se dividido
    subtitle_mode = Column(String, default="word_highlight")
    status = Column(String, default="processing")   # processing|ready|error
    file_path = Column(String, nullable=True)
    file_size_bytes = Column(Integer, nullable=True)
    created_at = Column(DateTime(timezone=True), default=utcnow)

    job = relationship("Job", back_populates="clips")
