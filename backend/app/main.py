import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.config import settings
from app.database import init_db
from app.routers import jobs, clips, references, schedule, settings as settings_router
from app.services.branding import migrate_legacy_branding
from app.workers.pipeline import reconcile_interrupted_jobs

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Inicializa banco de dados e diretórios de storage no startup."""
    logger.info("Starting ClipMint...")
    settings.ensure_dirs()
    await init_db()
    logger.info("Database initialized. Storage dirs ready.")

    # Marca global antiga → presets de cada nicho (idempotente).
    migrate_legacy_branding()

    # O pipeline roda dentro deste processo: jobs que ainda constam como "em
    # execução" são órfãos de um processo morto (reload, queda, Ctrl+C). Marca
    # como erro para o frontend parar de esperar — dá para retomar depois.
    interrupted = await reconcile_interrupted_jobs()
    if interrupted:
        logger.warning(
            f"{len(interrupted)} job(s) interrompido(s) marcado(s) como erro. "
            f"Retome com POST /api/jobs/<id>/retry."
        )

    yield
    logger.info("ClipMint shutting down.")


app = FastAPI(
    title="ClipMint API",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(jobs.router, prefix="/api")
app.include_router(clips.router, prefix="/api")
app.include_router(references.router, prefix="/api")
app.include_router(schedule.router, prefix="/api")
app.include_router(settings_router.router, prefix="/api")


@app.get("/health")
async def health() -> dict:
    return {"status": "ok"}
