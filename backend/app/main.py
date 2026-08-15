import hmac
import ipaddress
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from app.config import settings
from app.database import init_db
from app.routers import jobs, clips, references, schedule, settings as settings_router, video_enhance
from app.services.branding import migrate_legacy_branding
from app.workers.video_enhance_pipeline import reconcile_interrupted_enhancements
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

    # Mesma lógica para os tratamentos de vídeo da aba Melhorar vídeo.
    interrupted_videos = await reconcile_interrupted_enhancements()
    if interrupted_videos:
        logger.warning(
            f"{len(interrupted_videos)} tratamento(s) de vídeo interrompido(s) marcado(s) como falha."
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


def _is_loopback(host: str | None) -> bool:
    """O cliente é a própria máquina?

    Não dá para comparar com uma lista de literais: o proxy do Next chega como
    IPv4 mapeado em IPv6 (`::ffff:127.0.0.1`), que o `is_loopback` do módulo
    ipaddress só reconhece depois de desmapeado.
    """
    if not host:
        return False
    if host == "localhost":
        return True
    try:
        addr = ipaddress.ip_address(host)
    except ValueError:
        return False
    if isinstance(addr, ipaddress.IPv6Address) and addr.ipv4_mapped:
        addr = addr.ipv4_mapped
    return addr.is_loopback


@app.middleware("http")
async def require_local_or_token(request: Request, call_next):
    """Barra acesso direto à porta do backend vindo de fora da máquina.

    Quem chega pelo frontend já passou pela tela de login do Next; esta guarda
    cobre o caso de alguém apontar direto para a API — que, exposta na rede,
    dispararia jobs gastando crédito de AssemblyAI e Anthropic.
    """
    if settings.clipmint_password and request.url.path != "/health":
        if not _is_loopback(request.client.host if request.client else None):
            token = request.headers.get("x-clipmint-token", "")
            if not hmac.compare_digest(token, settings.clipmint_password):
                return JSONResponse({"detail": "Não autorizado"}, status_code=401)

    return await call_next(request)


app.include_router(jobs.router, prefix="/api")
app.include_router(clips.router, prefix="/api")
app.include_router(references.router, prefix="/api")
app.include_router(video_enhance.router, prefix="/api")
app.include_router(schedule.router, prefix="/api")
app.include_router(settings_router.router, prefix="/api")


@app.get("/health")
async def health() -> dict:
    return {"status": "ok"}
