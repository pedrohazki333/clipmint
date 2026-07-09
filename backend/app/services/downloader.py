import logging
from pathlib import Path
from typing import Optional
import yt_dlp

from app.config import settings

logger = logging.getLogger(__name__)


class VideoMetadata:
    def __init__(
        self,
        title: str,
        channel: str,
        duration: float,
        thumbnail_url: Optional[str],
        video_path: str,
        audio_path: str,
    ):
        self.title = title
        self.channel = channel
        self.duration = duration
        self.thumbnail_url = thumbnail_url
        self.video_path = video_path
        self.audio_path = audio_path


async def download_video(job_id: str, youtube_url: str) -> VideoMetadata:
    """
    Baixa vídeo e áudio separados do YouTube usando yt-dlp.

    Retorna metadados do vídeo incluindo caminhos para os arquivos baixados.
    O vídeo é baixado na melhor qualidade disponível (até 1080p).
    O áudio é extraído separadamente em formato WAV para melhor transcrição.
    """
    job_dir = settings.downloads_dir / job_id
    job_dir.mkdir(parents=True, exist_ok=True)

    video_path = str(job_dir / "video.mp4")
    audio_path = str(job_dir / "audio.wav")

    logger.info(f"[{job_id}] Downloading video from: {youtube_url}")

    # Baixa vídeo + áudio em uma única operação (melhor qualidade)
    ydl_opts_video = {
        "format": "bestvideo[height<=1080]+bestaudio/bestvideo[height<=1080]/best[height<=1080]/best",
        "outtmpl": video_path,
        "merge_output_format": "mp4",
        "quiet": True,
        "no_warnings": True,
    }

    with yt_dlp.YoutubeDL(ydl_opts_video) as ydl:
        info = ydl.extract_info(youtube_url, download=True)

    title = info.get("title", "Unknown Title")
    channel = info.get("uploader", info.get("channel", "Unknown Channel"))
    duration = float(info.get("duration", 0))
    thumbnail_url = info.get("thumbnail")

    logger.info(f"[{job_id}] Video downloaded: {title} ({duration:.0f}s)")

    # Extrai áudio em WAV para AssemblyAI
    logger.info(f"[{job_id}] Extracting audio...")
    ydl_opts_audio = {
        "format": "bestaudio/best",
        "outtmpl": str(job_dir / "audio_raw.%(ext)s"),
        "postprocessors": [
            {
                "key": "FFmpegExtractAudio",
                "preferredcodec": "wav",
                "preferredquality": "0",
            }
        ],
        "quiet": True,
        "no_warnings": True,
    }

    with yt_dlp.YoutubeDL(ydl_opts_audio) as ydl:
        ydl.extract_info(youtube_url, download=True)

    # yt-dlp gera o arquivo com nome baseado no template
    raw_audio = job_dir / "audio_raw.wav"
    if raw_audio.exists():
        raw_audio.rename(audio_path)

    logger.info(f"[{job_id}] Audio extracted to: {audio_path}")

    return VideoMetadata(
        title=title,
        channel=channel,
        duration=duration,
        thumbnail_url=thumbnail_url,
        video_path=video_path,
        audio_path=audio_path,
    )
