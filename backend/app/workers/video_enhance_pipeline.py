"""
Orquestrador da melhoria de vídeo.

Fluxo:
  pending → processing → done | failed

O vídeo já existe quando o job começa (foi enviado pelo usuário), então quase
nada aqui é fatal: se uma etapa do tratamento falhar, o job entrega o melhor
arquivo conseguido — no pior caso o próprio original — em vez de sumir com um
vídeo que o usuário tem e quer de volta.

`failed` fica reservado para o caso em que o arquivo enviado não é vídeo
legível, porque aí não há nada a entregar.
"""

import json
import logging
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import select

from app.config import settings
from app.database import AsyncSessionLocal
from app.models import VideoEnhanceJob
from app.services.video_enhance import EnhanceStepError, probe, run_enhancement

logger = logging.getLogger(__name__)

RUNNING_STATUSES = ("pending", "processing")

INTERRUPTED_MESSAGE = (
    "O servidor reiniciou no meio do tratamento. Envie o vídeo de novo."
)


def _summary(path: Path) -> str:
    """Resumo legível do arquivo, para a tela mostrar o antes/depois."""
    try:
        info = probe(path)
    except EnhanceStepError:
        return "não foi possível ler"
    mbps = (path.stat().st_size * 8) / max(1, _duration_or_one(path)) / 1_000_000
    return f"{info.width}x{info.height} · {info.fps:.0f}fps · {mbps:.1f} Mbps"


def _duration_or_one(path: Path) -> float:
    """Duração em segundos; 1 como piso para não dividir por zero no bitrate."""
    import subprocess

    try:
        out = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "csv=p=0", str(path)],
            capture_output=True, text=True, timeout=30,
        ).stdout.strip()
        return max(1.0, float(out))
    except (ValueError, OSError, subprocess.SubprocessError):
        return 1.0


async def _update(job_id: str, status: str | None = None, **kwargs) -> None:
    async with AsyncSessionLocal() as db:
        result = await db.execute(select(VideoEnhanceJob).where(VideoEnhanceJob.id == job_id))
        job = result.scalar_one_or_none()
        if not job:
            logger.error(f"[{job_id}] VideoEnhanceJob sumiu ao atualizar para '{status}'")
            return
        if status:
            job.status = status
        job.updated_at = datetime.now(timezone.utc)
        for key, value in kwargs.items():
            setattr(job, key, value)
        await db.commit()
        if status:
            logger.info(f"[{job_id}] Melhoria: status → {status}")


async def run_video_enhance_pipeline(job_id: str) -> None:
    """Roda o tratamento sobre o vídeo enviado. Nunca levanta."""
    async with AsyncSessionLocal() as db:
        result = await db.execute(select(VideoEnhanceJob).where(VideoEnhanceJob.id == job_id))
        job = result.scalar_one_or_none()
        if not job:
            logger.error(f"[{job_id}] VideoEnhanceJob não encontrado ao iniciar")
            return
        source = Path(job.source_video_path)

    work_dir = settings.video_enhance_dir / job_id

    try:
        # Lê a fonte antes de tudo: se nem isso funciona, o arquivo não é vídeo
        # e é o único caso em que não há o que entregar.
        try:
            source_summary = await _to_thread_summary(source)
        except EnhanceStepError as e:
            await _update(job_id, "failed", status_detail=None,
                          error_message=f"O arquivo enviado não é um vídeo legível ({e}).")
            return

        await _update(job_id, "processing", source_summary=source_summary,
                      status_detail="preparando", error_message=None)

        async def on_step(label: str) -> None:
            await _update(job_id, status_detail=label)

        result = await run_enhancement(source, work_dir, on_step=on_step)

        steps = {
            "aplicadas": result.steps_done,
            "dispensadas": result.skipped,
            "falhas": result.warnings,
        }
        await _update(
            job_id,
            "done",
            final_video_path=str(result.path),
            final_summary=await _to_thread_summary(result.path),
            steps_json=json.dumps(steps, ensure_ascii=False),
            status_detail=None,
            error_message="; ".join(result.warnings) if result.warnings else None,
        )
        logger.info(f"[{job_id}] Melhoria concluída → {result.path.name}")

    except Exception as e:  # noqa: BLE001 — o job não pode ficar preso em 'processing'
        logger.exception(f"[{job_id}] Tratamento quebrou por inteiro")
        await _update(job_id, "failed", status_detail=None,
                      error_message=f"Erro inesperado no tratamento: {e}")


async def _to_thread_summary(path: Path) -> str:
    import asyncio

    return await asyncio.to_thread(_summary, path)


async def reconcile_interrupted_enhancements() -> list[str]:
    """Solta no startup os jobs presos por um processo que morreu."""
    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(VideoEnhanceJob).where(VideoEnhanceJob.status.in_(RUNNING_STATUSES))
        )
        jobs = list(result.scalars().all())
        if not jobs:
            return []

        now = datetime.now(timezone.utc)
        for job in jobs:
            job.status = "failed"
            job.status_detail = None
            job.error_message = INTERRUPTED_MESSAGE
            job.updated_at = now
        await db.commit()
        return [job.id for job in jobs]
