import json
import logging
import shutil
from typing import List

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import delete, select, update
from sqlalchemy.orm import selectinload

from app.config import settings
from app.database import get_db
from app.models import Clip, Job, Transcript
from app.schemas import JobCreate, JobResponse, JobDetailResponse
from app.workers import joblock
from app.workers.pipeline import RUNNING_STATUSES, run_pipeline

logger = logging.getLogger(__name__)

router = APIRouter(tags=["jobs"])


@router.post("/jobs", response_model=JobResponse, status_code=201)
async def create_job(
    payload: JobCreate,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
) -> Job:
    """Cria um novo job de processamento e inicia o pipeline em background."""
    job = Job(
        youtube_url=payload.youtube_url,
        subtitle_mode=payload.subtitle_mode,
        layout_mode=payload.layout_mode,
        # Sem caixa informada, o pipeline detecta a facecam clip a clip
        facecam_rect=(
            payload.facecam_rect.model_dump_json() if payload.facecam_rect else None
        ),
        status="queued",
    )
    db.add(job)
    await db.commit()
    await db.refresh(job)

    logger.info(f"Job {job.id} created for URL: {payload.youtube_url}")
    background_tasks.add_task(run_pipeline, job.id)

    return job


@router.get("/jobs", response_model=List[JobResponse])
async def list_jobs(
    db: AsyncSession = Depends(get_db),
) -> List[Job]:
    """Retorna todos os jobs em ordem decrescente de criação."""
    result = await db.execute(
        select(Job).order_by(Job.created_at.desc())
    )
    return result.scalars().all()


@router.get("/jobs/{job_id}", response_model=JobDetailResponse)
async def get_job(
    job_id: str,
    db: AsyncSession = Depends(get_db),
) -> Job:
    """Retorna detalhes do job incluindo todos os clips gerados."""
    result = await db.execute(
        select(Job)
        .options(selectinload(Job.clips))
        .where(Job.id == job_id)
    )
    job = result.scalar_one_or_none()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return job


def _was_auto_detected(facecam_json: str | None) -> bool:
    """True se a caixa da facecam salva veio do detector (e não do usuário)."""
    if not facecam_json:
        return False
    try:
        stored = json.loads(facecam_json)
    except json.JSONDecodeError:
        return True  # ilegível: melhor detectar de novo
    return isinstance(stored, dict) and stored.get("method", "manual") != "manual"


@router.post("/jobs/{job_id}/retry", response_model=JobResponse, status_code=202)
async def retry_job(
    job_id: str,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
) -> Job:
    """
    Retoma um job que falhou ou foi interrompido, reaproveitando o que já ficou
    pronto: o vídeo baixado, a transcrição, a análise e os clips renderizados.
    Só o que falta é refeito — sem re-download e sem custo de API.

    Também serve para um job 'done' com clips que falharam: re-renderiza só eles.
    """
    result = await db.execute(select(Job).where(Job.id == job_id))
    job = result.scalar_one_or_none()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    owner = joblock.owner_pid(job_id)
    if job.status in RUNNING_STATUSES or owner is not None:
        raise HTTPException(
            status_code=409,
            detail="O job já está em processamento.",
        )

    job.status = "queued"
    job.error_message = None
    if _was_auto_detected(job.facecam_rect):
        # Caixa que veio da detecção é descartada — o retry re-detecta e pega as
        # melhorias do detector. A que o usuário informou à mão é preservada.
        job.facecam_rect = None
    # Clips que falharam voltam para a fila; os 'ready' são preservados.
    await db.execute(
        update(Clip)
        .where(Clip.job_id == job_id, Clip.status == "error")
        .values(status="processing")
    )
    await db.commit()
    await db.refresh(job)

    logger.info(f"Job {job_id} retomado (resume)")
    background_tasks.add_task(run_pipeline, job_id, True)

    return job


@router.delete("/jobs/{job_id}", status_code=204)
async def delete_job(
    job_id: str,
    db: AsyncSession = Depends(get_db),
) -> None:
    """
    Exclui o job e tudo associado a ele: clips e transcript no banco,
    vídeo/áudio baixados, clips renderizados e o JSON de palavras.

    Jobs em andamento também podem ser excluídos (cobre jobs travados após
    restart); o pipeline detecta a ausência do job e encerra sem crashar.
    """
    result = await db.execute(select(Job).where(Job.id == job_id))
    job = result.scalar_one_or_none()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    # Registros no banco (sem FK cascade configurado — remoção explícita)
    await db.execute(delete(Clip).where(Clip.job_id == job_id))
    await db.execute(delete(Transcript).where(Transcript.job_id == job_id))
    await db.delete(job)
    await db.commit()

    # Arquivos no storage (caminhos derivados do ID, não do banco)
    shutil.rmtree(settings.downloads_dir / job_id, ignore_errors=True)
    shutil.rmtree(settings.clips_dir / job_id, ignore_errors=True)
    words_json = settings.transcripts_dir / f"{job_id}_words.json"
    words_json.unlink(missing_ok=True)
    (settings.locks_dir / f"{job_id}.pid").unlink(missing_ok=True)

    logger.info(f"Job {job_id} deleted (records + storage)")
