"""
Face Tracker — rastreamento de rosto via MediaPipe Face Detection.

Usa FFmpeg para extrair frames (suporta qualquer codec: AV1, H.264, H.265, VP9…),
salva como JPEG temporário e processa com MediaPipe — evita o problema de
decodificação AV1 via OpenCV VideoCapture.

Retorna uma LINHA DO TEMPO de posições (keyframes suavizados), não uma média:
o clipper usa esses keyframes para mover o crop 9:16 acompanhando o rosto.

Suavização: filtro Gaussiano SIMÉTRICO (zero-lag — como o processamento é
offline, cada posição é suavizada olhando para frente E para trás, então o
crop nunca "corre atrás" do rosto como um filtro causal tipo EMA faria).
Cortes de cena são detectados antes da suavização e cada trecho é filtrado
separadamente — a troca de câmera continua instantânea, sem "deslize".

Fallback automático para crop centralizado se confiança < 40%.
"""

import asyncio
import glob
import logging
import os
import subprocess
import tempfile
from typing import Optional

logger = logging.getLogger(__name__)

_CONFIDENCE_THRESHOLD = 0.40

# Suavização da trajetória
_SAMPLE_INTERVAL = 0.2   # s entre amostras (5 fps) — denso o bastante para movimento fluido
_SMOOTH_SIGMA_S = 0.8    # desvio-padrão do kernel Gaussiano em segundos

# Salto maior que isso (fração da largura) = corte de cena → reposiciona na hora.
# Usado também pelo clipper para NÃO interpolar o crop através do corte.
SNAP_THRESHOLD = 0.15


def _fallback_result() -> dict:
    return {
        "center_x": 0.5,
        "center_y": 0.35,
        "confidence": 0.0,
        "method": "fallback_static",
        "keyframes": [],
    }


def _fill_gaps(raw: list[Optional[float]]) -> list[float]:
    """Preenche frames sem detecção: carrega a última posição válida
    (e preenche o início com a primeira válida)."""
    first_valid = next((v for v in raw if v is not None), 0.5)
    filled: list[float] = []
    last = first_valid
    for v in raw:
        if v is not None:
            last = v
        filled.append(last)
    return filled


def _gaussian_smooth(values: list[float], sigma_samples: float) -> list[float]:
    """Filtro Gaussiano simétrico (zero-lag) com padding de borda."""
    if len(values) < 3 or sigma_samples <= 0:
        return list(values)

    import numpy as np

    radius = max(1, int(3 * sigma_samples))
    x = np.arange(-radius, radius + 1)
    kernel = np.exp(-0.5 * (x / sigma_samples) ** 2)
    kernel /= kernel.sum()

    padded = np.pad(np.asarray(values, dtype=float), radius, mode="edge")
    return np.convolve(padded, kernel, mode="valid").tolist()


def _smooth(values: list[float], sample_interval: float) -> list[float]:
    """
    Divide a trajetória em trechos nos cortes de cena (salto > SNAP_THRESHOLD)
    e aplica o filtro Gaussiano em cada trecho separadamente — o movimento
    dentro do trecho fica fluido e o corte continua instantâneo.
    """
    segments: list[list[float]] = [[values[0]]]
    for prev, v in zip(values, values[1:]):
        if abs(v - prev) > SNAP_THRESHOLD:
            segments.append([v])
        else:
            segments[-1].append(v)

    sigma_samples = _SMOOTH_SIGMA_S / sample_interval
    smoothed: list[float] = []
    for seg in segments:
        smoothed.extend(_gaussian_smooth(seg, sigma_samples))
    return smoothed


def _track_faces_sync(
    video_path: str,
    start_time: float,
    end_time: float,
    sample_interval: float,
) -> dict:
    try:
        import cv2
        import mediapipe as mp
    except ImportError as exc:
        logger.warning(f"MediaPipe/OpenCV not available ({exc}), using static fallback")
        return _fallback_result()

    duration = end_time - start_time
    sample_fps = 1.0 / sample_interval

    with tempfile.TemporaryDirectory() as tmpdir:
        frame_pattern = os.path.join(tmpdir, "frame_%05d.jpg")

        # FFmpeg extrai frames — lida com AV1, H.264, H.265, VP9, etc.
        cmd = [
            "ffmpeg", "-y",
            "-ss", str(start_time),
            "-i", video_path,
            "-t", str(duration),
            "-vf", f"fps={sample_fps}",
            "-q:v", "2",
            frame_pattern,
        ]
        try:
            proc = subprocess.run(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=300,
            )
        except subprocess.TimeoutExpired:
            logger.warning("FFmpeg frame extraction timed out, using static fallback")
            return _fallback_result()

        if proc.returncode != 0:
            logger.warning(
                f"FFmpeg frame extraction failed: {proc.stderr.decode(errors='replace')[-400:]}"
            )
            return _fallback_result()

        frame_files = sorted(glob.glob(os.path.join(tmpdir, "frame_*.jpg")))
        if not frame_files:
            logger.info("No frames extracted, using static fallback")
            return _fallback_result()

        # Uma entrada por frame: center_x do rosto dominante ou None
        raw_positions: list[Optional[float]] = []
        detected = 0

        with mp.solutions.face_detection.FaceDetection(
            model_selection=1,
            min_detection_confidence=0.5,
        ) as face_detector:
            for frame_path in frame_files:
                frame = cv2.imread(frame_path)
                if frame is None:
                    raw_positions.append(None)
                    continue

                result = face_detector.process(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))
                if not result.detections:
                    raw_positions.append(None)
                    continue

                best = max(result.detections, key=lambda d: d.score[0])
                bbox = best.location_data.relative_bounding_box
                cx = max(0.0, min(1.0, bbox.xmin + bbox.width / 2.0))
                raw_positions.append(cx)
                detected += 1

    total_frames = len(raw_positions)
    confidence_ratio = detected / total_frames

    if detected == 0 or confidence_ratio < _CONFIDENCE_THRESHOLD:
        logger.info(
            f"Face detection confidence too low "
            f"({confidence_ratio:.0%} < {_CONFIDENCE_THRESHOLD:.0%}), using static fallback"
        )
        return _fallback_result()

    smoothed = _smooth(_fill_gaps(raw_positions), sample_interval)

    # Keyframes relativos ao início do clip: frame k (fps=N) ≈ t = k / N
    keyframes = [
        (round(k * sample_interval, 3), round(cx, 4))
        for k, cx in enumerate(smoothed)
    ]
    avg_cx = sum(smoothed) / len(smoothed)

    logger.info(
        f"Face tracking OK: {detected}/{total_frames} frames ({confidence_ratio:.0%}), "
        f"avg center_x={avg_cx:.3f}, range=[{min(smoothed):.3f}, {max(smoothed):.3f}]"
    )
    return {
        "center_x": round(avg_cx, 4),
        "center_y": 0.35,
        "confidence": round(confidence_ratio, 4),
        "method": "mediapipe",
        "keyframes": keyframes,
    }


async def track_faces(
    video_path: str,
    start_time: float,
    end_time: float,
    sample_interval: float = _SAMPLE_INTERVAL,
) -> dict:
    """
    Rastreia o rosto dominante no segmento e retorna a trajetória do centro X.

    Extrai frames via FFmpeg (suporta qualquer codec) e processa com MediaPipe
    em thread separada para não bloquear o event loop.

    Returns:
        {
            "center_x": float,     # média da trajetória (fallback/estatística)
            "center_y": float,     # fixo em 0.35
            "confidence": float,   # fração de frames com rosto detectado
            "method": str,         # "mediapipe" ou "fallback_static"
            "keyframes": list,     # [(t_rel_segundos, center_x), ...] suavizados
        }
    """
    logger.info(
        f"Tracking faces in [{start_time:.1f}s–{end_time:.1f}s] "
        f"({end_time - start_time:.1f}s, 1 frame/{sample_interval}s)"
    )
    return await asyncio.to_thread(
        _track_faces_sync, video_path, start_time, end_time, sample_interval
    )
