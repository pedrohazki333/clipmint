"""
Face Tracker — rastreamento de rosto via MediaPipe Face Detection.

Usa FFmpeg para extrair frames (suporta qualquer codec: AV1, H.264, H.265, VP9…),
salva como JPEG temporário e processa com MediaPipe — evita o problema de
decodificação AV1 via OpenCV VideoCapture.

Fallback automático para crop centralizado se confiança < 40%.
"""

import asyncio
import glob
import logging
import os
import subprocess
import tempfile

logger = logging.getLogger(__name__)

_CONFIDENCE_THRESHOLD = 0.40


def _fallback_result() -> dict:
    return {
        "center_x": 0.5,
        "center_y": 0.35,
        "confidence": 0.0,
        "method": "fallback_static",
    }


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
    sample_fps = 1.0 / sample_interval  # 0.5s interval → 2 fps

    with tempfile.TemporaryDirectory() as tmpdir:
        frame_pattern = os.path.join(tmpdir, "frame_%04d.jpg")

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
                timeout=120,
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

        detections: list[tuple[float, float]] = []  # (center_x, score)

        with mp.solutions.face_detection.FaceDetection(
            model_selection=1,
            min_detection_confidence=0.5,
        ) as face_detector:
            for frame_path in frame_files:
                frame = cv2.imread(frame_path)
                if frame is None:
                    continue

                rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                result = face_detector.process(rgb_frame)

                if not result.detections:
                    continue

                best = max(result.detections, key=lambda d: d.score[0])
                bbox = best.location_data.relative_bounding_box
                cx = bbox.xmin + bbox.width / 2.0
                cx = max(0.0, min(1.0, cx))
                detections.append((cx, float(best.score[0])))

    total_frames = len(frame_files)

    if not detections:
        logger.info("No faces detected in sampled frames, using static fallback")
        return _fallback_result()

    confidence_ratio = len(detections) / total_frames

    if confidence_ratio < _CONFIDENCE_THRESHOLD:
        logger.info(
            f"Face detection confidence too low "
            f"({confidence_ratio:.0%} < {_CONFIDENCE_THRESHOLD:.0%}), using static fallback"
        )
        return _fallback_result()

    # Média ponderada: score mais alto → mais peso no center_x final
    total_weight = sum(score for _, score in detections)
    weighted_cx = sum(cx * score for cx, score in detections) / total_weight

    logger.info(
        f"Face tracking OK: {len(detections)}/{total_frames} frames "
        f"({confidence_ratio:.0%}), center_x={weighted_cx:.3f}"
    )
    return {
        "center_x": round(weighted_cx, 4),
        "center_y": 0.35,
        "confidence": round(confidence_ratio, 4),
        "method": "mediapipe",
    }


async def track_faces(
    video_path: str,
    start_time: float,
    end_time: float,
    sample_interval: float = 0.5,
) -> dict:
    """
    Detecta o rosto dominante no segmento e retorna o centro X para crop 9:16.

    Extrai frames via FFmpeg (suporta qualquer codec) e processa com MediaPipe
    em thread separada para não bloquear o event loop.

    Returns:
        {
            "center_x": float,    # 0.0–1.0, média ponderada das detecções
            "center_y": float,    # fixo em 0.35
            "confidence": float,  # fração de frames com rosto detectado
            "method": str,        # "mediapipe" ou "fallback_static"
        }
    """
    logger.info(
        f"Tracking faces in [{start_time:.1f}s–{end_time:.1f}s] "
        f"({end_time - start_time:.1f}s, 1 frame/{sample_interval}s)"
    )
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(
        None, _track_faces_sync, video_path, start_time, end_time, sample_interval
    )
