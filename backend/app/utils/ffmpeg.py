import asyncio
import json
import logging
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


async def probe_video(video_path: str) -> dict:
    """
    Retorna metadados do vídeo via ffprobe (duração, dimensões, streams).
    """
    cmd = [
        "ffprobe", "-v", "quiet",
        "-print_format", "json",
        "-show_streams", "-show_format",
        video_path,
    ]
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await proc.communicate()
    if proc.returncode != 0:
        raise RuntimeError(f"ffprobe failed: {stderr.decode()}")
    return json.loads(stdout.decode())


async def get_video_dimensions(video_path: str) -> tuple[int, int]:
    """Retorna (width, height) do vídeo."""
    info = await probe_video(video_path)
    for stream in info.get("streams", []):
        if stream.get("codec_type") == "video":
            return int(stream["width"]), int(stream["height"])
    raise ValueError(f"No video stream found in {video_path}")


async def run_ffmpeg(*args: str, description: str = "") -> None:
    """
    Executa um comando ffmpeg e levanta erro se falhar.

    Args:
        *args: Argumentos do comando ffmpeg (sem o 'ffmpeg' inicial).
        description: Descrição para logging.
    """
    cmd = ["ffmpeg", "-y", *args]
    if description:
        logger.info(f"FFmpeg: {description}")
    logger.debug(f"FFmpeg command: {' '.join(cmd)}")

    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await proc.communicate()

    if proc.returncode != 0:
        error_output = stderr.decode(errors="replace")[-2000:]
        raise RuntimeError(f"FFmpeg failed ({description}): {error_output}")
