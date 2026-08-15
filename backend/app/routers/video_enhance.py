"""
Router da aba Melhorar vídeo — sobe um vídeo, recebe ele tratado.

Fluxo de uso:
  1. POST /video-enhance          (upload do vídeo) → cria e dispara em background
  2. GET  /video-enhance          → lista para o polling da tela
  3. GET  /video-enhance/{id}/video    → stream para o player (inline)
  4. GET  /video-enhance/{id}/download → download do arquivo tratado
"""

import json
import logging
import shutil
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, Depends, File, HTTPException, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import get_db
from app.models import VideoEnhanceJob
from app.schemas import VideoEnhanceJobResponse
from app.workers.video_enhance_pipeline import run_video_enhance_pipeline

logger = logging.getLogger(__name__)

router = APIRouter(tags=["video-enhance"])

_ALLOWED_EXT = {".mp4", ".mov", ".mkv", ".webm", ".m4v", ".avi"}
_MAX_BYTES = 500 * 1024 * 1024  # 500MB — mesmo teto dos clipes de referência


def _to_response(job: VideoEnhanceJob) -> VideoEnhanceJobResponse:
    steps: dict = {}
    if job.steps_json:
        try:
            steps = json.loads(job.steps_json)
        except json.JSONDecodeError:
            steps = {}

    return VideoEnhanceJobResponse(
        id=job.id,
        original_filename=job.original_filename,
        status=job.status,
        status_detail=job.status_detail,
        error_message=job.error_message,
        source_summary=job.source_summary,
        final_summary=job.final_summary,
        steps_applied=steps.get("aplicadas", []),
        steps_skipped=steps.get("dispensadas", []),
        has_video=bool(job.final_video_path and Path(job.final_video_path).exists()),
        created_at=job.created_at,
        updated_at=job.updated_at,
    )


async def _get_or_404(job_id: str, db: AsyncSession) -> VideoEnhanceJob:
    result = await db.execute(select(VideoEnhanceJob).where(VideoEnhanceJob.id == job_id))
    job = result.scalar_one_or_none()
    if not job:
        raise HTTPException(status_code=404, detail="Vídeo não encontrado")
    return job


def _playable_path(job: VideoEnhanceJob) -> Path:
    """Arquivo a servir, com o original como plano B.

    Se o tratamento falhou, servir o original é melhor que negar: o usuário
    subiu esse arquivo e quer poder baixá-lo de volta.
    """
    candidate = job.final_video_path or job.source_video_path
    if not candidate:
        raise HTTPException(status_code=400, detail=f"Nada para baixar (status: {job.status})")
    path = Path(candidate)
    if not path.exists():
        raise HTTPException(status_code=404, detail="Arquivo não encontrado no disco")
    return path


@router.post("/video-enhance", response_model=VideoEnhanceJobResponse, status_code=201)
async def create_video_enhance(
    background_tasks: BackgroundTasks,
    video: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
) -> VideoEnhanceJobResponse:
    """Recebe o vídeo e dispara o tratamento em background."""
    ext = Path(video.filename or "").suffix.lower()
    if ext not in _ALLOWED_EXT:
        raise HTTPException(
            status_code=422,
            detail=f"Formato inválido ({ext or 'sem extensão'}). "
                   f"Aceitos: {', '.join(sorted(_ALLOWED_EXT))}",
        )

    data = await video.read()
    if not data:
        raise HTTPException(status_code=422, detail="Arquivo de vídeo vazio")
    if len(data) > _MAX_BYTES:
        raise HTTPException(status_code=413, detail="Vídeo muito grande (máx. 500MB)")

    job = VideoEnhanceJob(
        source_video_path="",
        original_filename=video.filename,
        status="pending",
    )
    db.add(job)
    await db.commit()
    await db.refresh(job)

    work_dir = settings.video_enhance_dir / job.id
    work_dir.mkdir(parents=True, exist_ok=True)
    source_path = work_dir / f"original{ext}"
    source_path.write_bytes(data)

    job.source_video_path = str(source_path)
    await db.commit()
    await db.refresh(job)

    logger.info(f"VideoEnhance {job.id} criado ({video.filename}, {len(data)/1e6:.1f}MB)")
    background_tasks.add_task(run_video_enhance_pipeline, job.id)

    return _to_response(job)


@router.get("/video-enhance", response_model=list[VideoEnhanceJobResponse])
async def list_video_enhance(db: AsyncSession = Depends(get_db)) -> list[VideoEnhanceJobResponse]:
    """Lista os tratamentos em ordem decrescente de criação."""
    result = await db.execute(
        select(VideoEnhanceJob).order_by(VideoEnhanceJob.created_at.desc())
    )
    return [_to_response(j) for j in result.scalars().all()]


@router.get("/video-enhance/{job_id}", response_model=VideoEnhanceJobResponse)
async def get_video_enhance(
    job_id: str, db: AsyncSession = Depends(get_db)
) -> VideoEnhanceJobResponse:
    return _to_response(await _get_or_404(job_id, db))


@router.get("/video-enhance/{job_id}/video")
async def stream_video(job_id: str, db: AsyncSession = Depends(get_db)) -> FileResponse:
    """Serve inline, para o <video> da página (o /download manda attachment)."""
    job = await _get_or_404(job_id, db)
    return FileResponse(path=str(_playable_path(job)), media_type="video/mp4")


@router.get("/video-enhance/{job_id}/download")
async def download_video(job_id: str, db: AsyncSession = Depends(get_db)) -> FileResponse:
    """Download do vídeo tratado (ou do original, se o tratamento falhou)."""
    job = await _get_or_404(job_id, db)
    path = _playable_path(job)
    # Nome do arquivo do usuário com sufixo, para ele não confundir com o original
    stem = Path(job.original_filename or "video").stem
    return FileResponse(
        path=str(path), media_type="video/mp4", filename=f"{stem}_1080p.mp4"
    )


@router.delete("/video-enhance/{job_id}", status_code=204)
async def delete_video_enhance(job_id: str, db: AsyncSession = Depends(get_db)) -> None:
    """Remove o job e os arquivos dele (original + tratado)."""
    job = await _get_or_404(job_id, db)
    await db.delete(job)
    await db.commit()
    shutil.rmtree(settings.video_enhance_dir / job_id, ignore_errors=True)
    logger.info(f"VideoEnhance {job_id} excluído (registro + arquivos)")
