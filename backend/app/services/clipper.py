"""
Serviço de corte e crop de vídeo usando FFmpeg.

Responsável por:
  1. Cortar o segmento com dual seek (fast seek + seek preciso frame-a-frame).
  2. Aplicar crop 9:16 posicionado pelo face tracker (fallback centralizado).
  3. Escalar para 1080x1920 com filtro lanczos.
  4. Queimar legendas ASS — tudo em uma única passagem FFmpeg.

Filtergraph: crop → scale:lanczos → ass  (ordem garante zero dupla interpolação)
Resolução de saída: 1080x1920 (Full HD vertical).
"""

import logging
from pathlib import Path

from app.config import settings
from app.services.face_tracker import track_faces
from app.services.subtitler import generate_ass_subtitles
from app.utils.ffmpeg import run_ffmpeg, get_video_dimensions, probe_video

logger = logging.getLogger(__name__)

OUTPUT_WIDTH = 1080
OUTPUT_HEIGHT = 1920
SEEK_PREROLL = 2.0  # segundos de margem do fast seek para o seek preciso


async def cut_and_crop(
    job_id: str,
    clip_id: str,
    video_path: str,
    start_time: float,
    end_time: float,
    words: list[dict],
    subtitle_mode: str,
) -> tuple[str, int]:
    """
    Corta o segmento do vídeo, aplica crop 9:16 e queima legendas em uma passagem.

    Args:
        job_id: ID do job para logging e organização dos arquivos.
        clip_id: ID do clip para nomeação do arquivo de saída.
        video_path: Caminho do vídeo original.
        start_time: Início do clip em segundos.
        end_time: Fim do clip em segundos.
        words: Lista de palavras com timestamps para geração de legendas.
        subtitle_mode: 'word_highlight', 'traditional', ou 'none'.

    Returns:
        Tupla (output_path, file_size_bytes).
    """
    clip_dir = settings.clips_dir / job_id
    clip_dir.mkdir(parents=True, exist_ok=True)

    duration = end_time - start_time
    logger.info(
        f"[{job_id}] Cutting clip {clip_id}: "
        f"[{start_time:.1f}s–{end_time:.1f}s] ({duration:.1f}s)"
    )

    # Face tracking: detecta onde o rosto está no segmento para posicionar o crop
    tracking = await track_faces(video_path, start_time, end_time)
    logger.info(
        f"[{job_id}] Face tracking: method={tracking['method']}, "
        f"center_x={tracking['center_x']:.3f}, confidence={tracking['confidence']:.0%}"
    )

    src_width, src_height = await get_video_dimensions(video_path)
    logger.info(f"[{job_id}] Source: {src_width}x{src_height}")

    crop_filter = _build_crop_filter(
        src_width, src_height,
        center_x=tracking["center_x"],
        center_y=tracking["center_y"],
    )
    scale_filter = f"scale={OUTPUT_WIDTH}:{OUTPUT_HEIGHT}:flags=lanczos"

    # Monta filtergraph — ordem correta: crop → scale → legendas
    if subtitle_mode != "none":
        ass_path = str(clip_dir / f"{clip_id}.ass")
        generate_ass_subtitles(
            words=words,
            start_time=start_time,
            end_time=end_time,
            subtitle_mode=subtitle_mode,
            output_path=ass_path,
        )
        vf = f"{crop_filter},{scale_filter},ass={_escape_filter_path(ass_path)}"
    else:
        vf = f"{crop_filter},{scale_filter}"

    # Dual seek: fast seek (keyframe) + seek preciso frame-a-frame
    approx_start = max(0.0, start_time - SEEK_PREROLL)
    fine_offset = start_time - approx_start

    final_path = str(clip_dir / f"{clip_id}.mp4")

    await run_ffmpeg(
        "-ss", str(approx_start),
        "-i", video_path,
        "-ss", str(fine_offset),
        "-t", str(duration),
        "-vf", vf,
        "-c:v", "libx264",
        "-preset", "slow",
        "-crf", "20",
        "-b:v", "4000k",
        "-maxrate", "8000k",
        "-bufsize", "8000k",
        "-c:a", "aac",
        "-b:a", "192k",
        final_path,
        description=f"Render clip {clip_id}",
    )

    file_size = Path(final_path).stat().st_size
    await _log_clip_quality(job_id, clip_id, final_path, file_size)

    return final_path, file_size


async def _log_clip_quality(
    job_id: str,
    clip_id: str,
    path: str,
    file_size: int,
) -> None:
    size_mb = file_size / 1024 / 1024
    try:
        info = await probe_video(path)
        bitrate_kbps = int(info.get("format", {}).get("bit_rate", 0)) // 1000
        width, height = 0, 0
        for stream in info.get("streams", []):
            if stream.get("codec_type") == "video":
                width = int(stream["width"])
                height = int(stream["height"])
                break
        logger.info(
            f"[{job_id}] Clip {clip_id} quality — "
            f"size={size_mb:.1f}MB, bitrate={bitrate_kbps}kbps, resolution={width}x{height}"
        )
    except Exception as exc:
        logger.warning(f"[{job_id}] Quality probe failed: {exc}")
        logger.info(f"[{job_id}] Clip {clip_id} ready: {size_mb:.1f}MB")


def _escape_filter_path(path: str) -> str:
    """Escapa o caminho para uso seguro dentro de um filtro FFmpeg (evita quebra no ass=)."""
    return path.replace("\\", "\\\\").replace("'", "\\'").replace(":", "\\:")


def _build_crop_filter(
    src_width: int,
    src_height: int,
    center_x: float = 0.5,
    center_y: float = 0.35,
) -> str:
    """
    Constrói o filtro crop= para recorte 9:16.

    Calcula a maior área 9:16 que cabe no vídeo fonte,
    posicionada em (center_x, center_y) com clamp nos limites.
    Não inclui scale= — composto separadamente para manter a ordem do filtergraph.
    """
    target_ratio = 9 / 16

    if src_width / src_height > target_ratio:
        # Vídeo mais largo que 9:16 → limitar pela altura
        crop_h = src_height
        crop_w = int(src_height * target_ratio)
    else:
        # Vídeo mais estreito que 9:16 → limitar pela largura
        crop_w = src_width
        crop_h = int(src_width / target_ratio)

    cx = int(src_width * center_x - crop_w / 2)
    cy = int(src_height * center_y - crop_h / 2)

    cx = max(0, min(cx, src_width - crop_w))
    cy = max(0, min(cy, src_height - crop_h))

    return f"crop={crop_w}:{crop_h}:{cx}:{cy}"
