import io
import logging

from fastapi import APIRouter, File, HTTPException, UploadFile
from fastapi.responses import FileResponse
from PIL import Image, UnidentifiedImageError

from app.config import settings

logger = logging.getLogger(__name__)

router = APIRouter(tags=["settings"])

_MAX_UPLOAD_BYTES = 5 * 1024 * 1024
_MAX_DIMENSION = 1024


def _watermark_file():
    return settings.branding_dir / "watermark.png"


@router.post("/settings/watermark", status_code=201)
async def upload_watermark(file: UploadFile = File(...)) -> dict:
    """
    Recebe a logo/marca d'água do usuário (PNG/JPEG/WebP), normaliza para
    PNG RGBA (transparência preservada) e salva em storage/branding/.
    """
    data = await file.read()
    if len(data) > _MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="Imagem muito grande (máx. 5MB)")

    try:
        img = Image.open(io.BytesIO(data))
        img.verify()  # valida integridade
        img = Image.open(io.BytesIO(data)).convert("RGBA")
    except (UnidentifiedImageError, OSError):
        raise HTTPException(
            status_code=400, detail="Arquivo inválido: envie uma imagem PNG, JPEG ou WebP"
        )

    img.thumbnail((_MAX_DIMENSION, _MAX_DIMENSION), Image.LANCZOS)

    settings.branding_dir.mkdir(parents=True, exist_ok=True)
    path = _watermark_file()
    img.save(path, format="PNG")
    logger.info(f"Watermark saved: {path} ({img.width}x{img.height})")

    return {"status": "ok", "width": img.width, "height": img.height}


@router.get("/settings/watermark")
async def get_watermark() -> FileResponse:
    """Retorna a marca d'água atual (404 se não configurada)."""
    path = _watermark_file()
    if not path.exists():
        raise HTTPException(status_code=404, detail="Nenhuma marca d'água configurada")
    return FileResponse(str(path), media_type="image/png")


@router.delete("/settings/watermark", status_code=204)
async def delete_watermark() -> None:
    """Remove a marca d'água configurada."""
    path = _watermark_file()
    if path.exists():
        path.unlink()
        logger.info("Watermark removed")
