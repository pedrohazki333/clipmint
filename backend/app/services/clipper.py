"""
Serviço de corte e composição de clips usando FFmpeg.

Layout final 1080x1920:
  - Capa estática no topo (print de expressão marcante — layout.generate_cover)
  - Banner de título (pílula vermelha — layout.generate_banner) sobre a emenda
  - Vídeo com crop dinâmico (face tracking) rodando embaixo, com legendas

Filtergraph: [sendcmd →] crop → scale → pad(canvas) → overlay(capa)
             → overlay(banner) → ass
Tudo em uma única passagem FFmpeg.
"""

import asyncio
import logging
from pathlib import Path

from app.config import settings
from app.services.face_tracker import track_faces, SNAP_THRESHOLD
from app.services.layout import generate_banner, generate_cover, COVER_H
from app.services.subtitler import generate_ass_subtitles
from app.services.watermark import detect_brand_regions, user_watermark_path
from app.utils.ffmpeg import run_ffmpeg, get_video_dimensions, probe_video

logger = logging.getLogger(__name__)

CANVAS_W = 1080
CANVAS_H = 1920

# Área do vídeo (parte inferior do canvas); a capa ocupa o topo
VIDEO_W = CANVAS_W
VIDEO_H = CANVAS_H - COVER_H  # 1152

# Centro vertical do banner fica exatamente na emenda capa/vídeo
BANNER_CENTER_Y = COVER_H

# Passo de interpolação dos comandos de crop (s) — 1/30s = atualização por frame
TRACK_CMD_INTERVAL = 1 / 30


async def cut_and_crop(
    job_id: str,
    clip_id: str,
    video_path: str,
    start_time: float,
    end_time: float,
    words: list[dict],
    subtitle_mode: str,
    banner_text: str = "",
) -> tuple[str, int]:
    """
    Corta o segmento e monta o clip final: capa + banner + vídeo com face
    tracking e legendas.

    Args:
        job_id: ID do job para logging e organização dos arquivos.
        clip_id: ID do clip para nomeação do arquivo de saída.
        video_path: Caminho do vídeo original.
        start_time: Início do clip em segundos.
        end_time: Fim do clip em segundos.
        words: Lista de palavras com timestamps para geração de legendas.
        subtitle_mode: 'word_highlight', 'traditional', ou 'none'.
        banner_text: Título exibido na pílula vermelha (vazio = sem banner).

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

    # Detecta marcas de terceiros primeiro (a capa precisa das regiões);
    # face tracking + capa rodam em paralelo na sequência
    watermark = user_watermark_path()
    brand = await asyncio.to_thread(
        detect_brand_regions, video_path, start_time, end_time
    )
    qr_regions = brand["qr"]
    all_regions = brand["qr"] + brand["static"]

    cover_path = str(clip_dir / f"{clip_id}_cover.png")
    tracking, cover_method = await asyncio.gather(
        track_faces(video_path, start_time, end_time),
        asyncio.to_thread(
            generate_cover, video_path, start_time, end_time, cover_path,
            watermark_path=watermark,
            qr_regions=brand["qr"],
            static_regions=brand["static"],
        ),
    )
    logger.info(
        f"[{job_id}] Face tracking: method={tracking['method']}, "
        f"keyframes={len(tracking.get('keyframes', []))}, "
        f"confidence={tracking['confidence']:.0%} | cover: {cover_method} | "
        f"QR: {len(qr_regions)} | static marks: {len(brand['static'])} | "
        f"watermark: {'yes' if watermark else 'no'}"
    )

    src_width, src_height = await get_video_dimensions(video_path)
    logger.info(f"[{job_id}] Source: {src_width}x{src_height}")

    crop_w, crop_h = _crop_dimensions(src_width, src_height, VIDEO_W / VIDEO_H)
    cy = _clamp(
        int(src_height * tracking["center_y"] - crop_h / 2), 0, src_height - crop_h
    )

    keyframes = tracking.get("keyframes", [])
    if tracking["method"] == "mediapipe" and len(keyframes) >= 2:
        # Crop dinâmico: sendcmd atualiza o x do crop ao longo do tempo
        cmd_path = str(clip_dir / f"{clip_id}_track.cmd")
        x0 = _write_track_commands(cmd_path, keyframes, duration, src_width, crop_w)
        crop_filter = (
            f"sendcmd=f={_escape_filter_path(cmd_path)},"
            f"crop@dyn={crop_w}:{crop_h}:{x0}:{cy}"
        )
    else:
        x0 = _crop_x(tracking["center_x"], src_width, crop_w)
        crop_filter = f"crop={crop_w}:{crop_h}:{x0}:{cy}"

    # ── Monta o filter_complex ────────────────────────────────────────────────
    inputs = ["-ss", str(start_time), "-i", video_path]
    n_inputs = 1
    parts: list[str] = []

    # Neutralização de marcas de terceiros ANTES do crop (coordenadas da
    # fonte): delogo borra QRs e logos de canal; a logo do usuário é
    # sobreposta nos QRs. Como acontece pré-crop, acompanha o face tracking.
    src_label = "0:v"
    if all_regions:
        delogos = ",".join(
            _delogo_filter(x, y, w, h, src_width, src_height)
            for (x, y, w, h) in all_regions
        )
        parts.append(f"[{src_label}]{delogos}[clean]")
        src_label = "clean"

        if watermark and qr_regions:
            from PIL import Image

            logo_w, logo_h = Image.open(watermark).size
            wm_idx = n_inputs
            inputs += ["-i", watermark]
            n_inputs += 1

            wm_labels = [f"wm{i}" for i in range(len(qr_regions))]
            if len(qr_regions) > 1:
                parts.append(
                    f"[{wm_idx}:v]split={len(qr_regions)}"
                    + "".join(f"[{l}]" for l in wm_labels)
                )
            else:
                parts.append(f"[{wm_idx}:v]null[{wm_labels[0]}]")

            for i, (x, y, w, h) in enumerate(qr_regions):
                scale = min(w * 0.95 / logo_w, h * 0.95 / logo_h)
                lw = max(2, int(logo_w * scale) // 2 * 2)
                lh = max(2, int(logo_h * scale) // 2 * 2)
                ox = x + (w - lw) // 2
                oy = y + (h - lh) // 2
                parts.append(f"[{wm_labels[i]}]scale={lw}:{lh}[ws{i}]")
                parts.append(f"[{src_label}][ws{i}]overlay={ox}:{oy}[qr{i}]")
                src_label = f"qr{i}"

    # vídeo → área inferior do canvas (pad preserva fps/timing do vídeo)
    cover_idx = n_inputs
    inputs += ["-i", cover_path]
    n_inputs += 1
    parts.append(
        f"[{src_label}]{crop_filter},"
        f"scale={VIDEO_W}:{VIDEO_H}:flags=lanczos,"
        f"pad={CANVAS_W}:{CANVAS_H}:0:{COVER_H}:black[base]"
    )
    parts.append(f"[base][{cover_idx}:v]overlay=0:0[withcover]")
    last_label = "withcover"

    if banner_text.strip():
        banner_path = str(clip_dir / f"{clip_id}_banner.png")
        _, banner_h = await asyncio.to_thread(
            generate_banner, banner_text, banner_path
        )
        banner_y = BANNER_CENTER_Y - banner_h // 2
        banner_idx = n_inputs
        inputs += ["-i", banner_path]
        n_inputs += 1
        parts.append(
            f"[{last_label}][{banner_idx}:v]"
            f"overlay=(main_w-overlay_w)/2:{banner_y}[withbanner]"
        )
        last_label = "withbanner"

    if subtitle_mode != "none":
        ass_path = str(clip_dir / f"{clip_id}.ass")
        generate_ass_subtitles(
            words=words,
            start_time=start_time,
            end_time=end_time,
            subtitle_mode=subtitle_mode,
            output_path=ass_path,
        )
        parts.append(f"[{last_label}]ass={_escape_filter_path(ass_path)}[outv]")
    else:
        parts.append(f"[{last_label}]null[outv]")

    chain = ";".join(parts)

    final_path = str(clip_dir / f"{clip_id}.mp4")

    # Input seeking (-ss antes de -i) é frame-accurate com re-encode e zera o
    # timestamp do filtergraph — os keyframes do tracking casam 1:1 com o sendcmd.
    await run_ffmpeg(
        *inputs,
        "-t", str(duration),
        "-filter_complex", chain,
        "-map", "[outv]",
        "-map", "0:a?",
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


def _delogo_filter(
    x: int, y: int, w: int, h: int, src_w: int, src_h: int
) -> str:
    """Filtro delogo com a região clampada aos limites exigidos pelo FFmpeg
    (a região precisa ficar estritamente dentro do frame)."""
    x = max(1, min(x, src_w - 3))
    y = max(1, min(y, src_h - 3))
    w = max(2, min(w, src_w - x - 1))
    h = max(2, min(h, src_h - y - 1))
    return f"delogo=x={x}:y={y}:w={w}:h={h}"


def _crop_dimensions(
    src_width: int, src_height: int, target_ratio: float
) -> tuple[int, int]:
    """Maior área com a proporção alvo que cabe no vídeo fonte (dimensões pares)."""
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
