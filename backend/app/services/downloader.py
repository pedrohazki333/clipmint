import asyncio
import logging
from dataclasses import dataclass
from typing import Optional

import yt_dlp

from app.config import settings
from app.utils.ffmpeg import run_ffmpeg

logger = logging.getLogger(__name__)


@dataclass
class VideoMetadata:
    title: str
    channel: str
    duration: float
    thumbnail_url: Optional[str]
    video_path: str
    audio_path: str


def _download_sync(youtube_url: str, video_path: str) -> dict:
    """Baixa o vídeo com yt-dlp (bloqueante — executar fora do event loop)."""
    # Até 4K: o crop 9:16 usa só ~56% da largura do vídeo — fonte 1080p vira
    # upscale no clip final. Com fonte 2160p o crop sai em resolução nativa.
    ydl_opts = {
        "format": "bestvideo[height<=2160]+bestaudio/bestvideo[height<=2160]/best[height<=2160]/best",
        "outtmpl": video_path,
        "merge_output_format": "mp4",
        "quiet": True,
        "no_warnings": True,
    }
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        return ydl.extract_info(youtube_url, download=True)


async def download_video(job_id: str, youtube_url: str) -> VideoMetadata:
    """
    Baixa o vídeo do YouTube (uma única vez) e extrai o áudio localmente.

    O download roda em thread separada para não bloquear o event loop —
    downloads longos não podem travar a API enquanto o frontend faz polling.
    O áudio é extraído do arquivo já baixado via FFmpeg (WAV mono 16kHz,
    suficiente para transcrição e muito menor que WAV full quality).
    """
    job_dir = settings.downloads_dir / job_id
    job_dir.mkdir(parents=True, exist_ok=True)

    video_path = str(job_dir / "video.mp4")
    audio_path = str(job_dir / "audio.wav")

    logger.info(f"[{job_id}] Downloading video from: {youtube_url}")
    info = await asyncio.to_thread(_download_sync, youtube_url, video_path)

    title = info.get("title", "Unknown Title")
    channel = info.get("uploader") or info.get("channel") or "Unknown Channel"
    duration = float(info.get("duration") or 0)
    thumbnail_url = info.get("thumbnail")

    logger.info(f"[{job_id}] Video downloaded: {title} ({duration:.0f}s)")

    # Extrai o áudio do arquivo local — evita baixar o vídeo uma segunda vez
    logger.info(f"[{job_id}] Extracting audio...")
    await run_ffmpeg(
        "-i", video_path,
        "-vn",
        "-acodec", "pcm_s16le",
        "-ar", "16000",
        "-ac", "1",
        audio_path,
        description=f"Extract audio for job {job_id}",
    )
    logger.info(f"[{job_id}] Audio extracted to: {audio_path}")

    return VideoMetadata(
        title=title,
        channel=channel,
        duration=duration,
        thumbnail_url=thumbnail_url,
        video_path=video_path,
        audio_path=audio_path,
    )
