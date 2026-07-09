"""
Serviço de corte e crop de vídeo usando FFmpeg.

Responsável por:
  1. Cortar o segmento com seek preciso (input seeking é frame-accurate em re-encode).
  2. Aplicar crop 9:16 dinâmico que acompanha o rosto (face tracker via sendcmd),
     com fallback para crop estático centralizado.
  3. Escalar para 1080x1920 com filtro lanczos.
  4. Queimar legendas ASS — tudo em uma única passagem FFmpeg.

Filtergraph: [sendcmd →] crop → scale:lanczos → ass
Resolução de saída: 1080x1920 (Full HD vertical).
"""

import logging
from pathlib import Path

from app.config import settings
from app.services.face_tracker import track_faces, SNAP_THRESHOLD
from app.services.subtitler import generate_ass_subtitles
from app.utils.ffmpeg import run_ffmpeg, get_video_dimensions, probe_video

logger = logging.getLogger(__name__)

OUTPUT_WIDTH = 1080
OUTPUT_HEIGHT = 1920

# Passo de interpolação dos comandos de crop (s) — 1/30s = atualização por frame,
# cada frame do vídeo recebe sua própria posição (deltas de ~1px, movimento contínuo)
TRACK_CMD_INTERVAL = 1 / 30


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
    Corta o segmento do vídeo, aplica crop 9:16 com face tracking e queima
    legendas em uma passagem.

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

    # Face tracking: trajetória do rosto no segmento para posicionar o crop
    tracking = await track_faces(video_path, start_time, end_time)
    logger.info(
        f"[{job_id}] Face tracking: method={tracking['method']}, "
        f"keyframes={len(tracking.get('keyframes', []))}, "
        f"confidence={tracking['confidence']:.0%}"
    )

    src_width, src_height = await get_video_dimensions(video_path)
    logger.info(f"[{job_id}] Source: {src_width}x{src_height}")

    crop_w, crop_h = _crop_dimensions(src_width, src_height)
    cy = _clamp(
        int(src_height * tracking["center_y"] - crop_h / 2), 0, src_height - crop_h
    )

    keyframes = tracking.get("keyframes", [])
    if tracking["method"] == "mediapipe" and len(keyframes) >= 2:
        # Crop dinâmico: sendcmd atualiza o x do crop ao longo do tempo
        cmd_path = str(clip_dir / f"{clip_id}_track.cmd")
        x0 = _write_track_commands(
            cmd_path, keyframes, duration, src_width, crop_w
        )
        crop_filter = (
            f"sendcmd=f={_escape_filter_path(cmd_path)},"
            f"crop@dyn={crop_w}:{crop_h}:{x0}:{cy}"
        )
    else:
        x0 = _crop_x(tracking["center_x"], src_width, crop_w)
        crop_filter = f"crop={crop_w}:{crop_h}:{x0}:{cy}"

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

    final_path = str(clip_dir / f"{clip_id}.mp4")

    # Input seeking (-ss antes de -i) é frame-accurate com re-encode e zera o
    # timestamp do filtergraph — os keyframes do tracking (relativos ao início
    # do clip) casam 1:1 com o tempo visto pelo sendcmd.
    await run_ffmpeg(
        "-ss", str(start_time),
        "-i", video_path,
        "-t", str(duration),
        "-vf", vf,
        "-c:v", "libx264",
        "-preset", "slow",
        "-crf", "18",
        "-maxrate", "12000k",
        "-bufsize", "24000k",
        "-profile:v", "high",
        "-pix_fmt", "yuv420p",
        "-c:a", "aac",
        "-b:a", "192k",
        final_path,
        description=f"Render clip {clip_id}",
    )

    file_size = Path(final_path).stat().st_size
    await _log_clip_quality(job_id, clip_id, final_path, file_size)

    return final_path, file_size


def _write_track_commands(
    cmd_path: str,
    keyframes: list[tuple[float, float]],
    duration: float,
    src_width: int,
    crop_w: int,
) -> int:
    """
    Gera o arquivo sendcmd com a posição x do crop interpolada linearmente
    entre os keyframes do face tracker, em passos de TRACK_CMD_INTERVAL.

    Retorna o x inicial (para o valor default do filtro crop).
    """
    lines = []
    last_x = None
    n_steps = int(duration / TRACK_CMD_INTERVAL) + 1
    for i in range(n_steps):
        t = i * TRACK_CMD_INTERVAL
        cx = _interp(keyframes, t)
        x = _crop_x(cx, src_width, crop_w)
        if x != last_x:  # não emite comandos redundantes
            lines.append(f"{t:.3f} crop@dyn x {x};")
            last_x = x

    with open(cmd_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")

    x0 = _crop_x(keyframes[0][1], src_width, crop_w)
    logger.debug(f"Track commands written: {cmd_path} ({len(lines)} updates)")
    return x0


def _interp(keyframes: list[tuple[float, float]], t: float) -> float:
    """
    Interpolação linear de center_x nos keyframes (clampa nas pontas).

    Saltos maiores que SNAP_THRESHOLD são cortes de cena: o crop NÃO desliza
    através deles — segura a posição anterior e pula de uma vez no keyframe.
    """
    if t <= keyframes[0][0]:
        return keyframes[0][1]
    for (t0, x0), (t1, x1) in zip(keyframes, keyframes[1:]):
        if t <= t1:
            if t1 == t0 or abs(x1 - x0) > SNAP_THRESHOLD:
                return x0 if t < t1 else x1
            frac = (t - t0) / (t1 - t0)
            return x0 + frac * (x1 - x0)
    return keyframes[-1][1]


def _crop_dimensions(src_width: int, src_height: int) -> tuple[int, int]:
    """Maior área 9:16 que cabe no vídeo fonte (largura par para o x264)."""
    target_ratio = 9 / 16
    if src_width / src_height > target_ratio:
        crop_h = src_height
        crop_w = int(src_height * target_ratio)
    else:
        crop_w = src_width
        crop_h = int(src_width / target_ratio)
    return crop_w - (crop_w % 2), crop_h - (crop_h % 2)


def _crop_x(center_x: float, src_width: int, crop_w: int) -> int:
    """Posição x do crop para centralizar center_x, clampada nos limites."""
    return _clamp(int(src_width * center_x - crop_w / 2), 0, src_width - crop_w)


def _clamp(v: int, lo: int, hi: int) -> int:
    return max(lo, min(v, hi))


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
    """Escapa o caminho para uso seguro dentro de um filtro FFmpeg."""
    return path.replace("\\", "\\\\").replace("'", "\\'").replace(":", "\\:")
