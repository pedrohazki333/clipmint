import logging
from typing import List

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.database import get_db
from app.models import Job
from app.schemas import JobCreate, JobResponse, JobDetailResponse
from app.workers.pipeline import run_pipeline

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
