import io
import json
import logging
import re

from fastapi import APIRouter, File, HTTPException, UploadFile
from fastapi.responses import FileResponse
from PIL import Image, UnidentifiedImageError
from pydantic import BaseModel, field_validator

from app.config import settings
from app.services.layout import (
    BAR_DEFAULT_BG_HEX,
    BAR_DEFAULT_FONT,
    BAR_DEFAULT_TEXT_HEX,
    BAR_FONTS,
    available_bar_fonts,
    load_banner_colors,
    load_bar_style,
)

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


# ─── Cores do banner ──────────────────────────────────────────────────────────

_HEX_RE = re.compile(r"^#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{6})$")


def _banner_colors_file():
    return settings.branding_dir / "banner_colors.json"


def _normalize_hex(value: str) -> str:
    v = value.lstrip("#")
    if len(v) == 3:
        v = "".join(c * 2 for c in v)
    return f"#{v.upper()}"


class BannerColors(BaseModel):
    bg_color: str
    text_color: str

    @field_validator("bg_color", "text_color")
    @classmethod
    def _valid_hex(cls, v: str) -> str:
        v = v.strip()
        if not _HEX_RE.match(v):
            raise ValueError("Cor inválida: use hexadecimal no formato #RRGGBB (ex: #ED2828)")
        return _normalize_hex(v)


@router.get("/settings/banner-colors")
async def get_banner_colors() -> dict:
    """Cores atuais do banner (padrões se nada foi customizado)."""
    bg, text, customized = load_banner_colors()
    return {"bg_color": bg, "text_color": text, "customized": customized}


@router.put("/settings/banner-colors")
async def set_banner_colors(colors: BannerColors) -> dict:
    """Define as cores do banner (fundo da pílula e fonte) em hexadecimal."""
    settings.branding_dir.mkdir(parents=True, exist_ok=True)
    _banner_colors_file().write_text(
        json.dumps({"bg_color": colors.bg_color, "text_color": colors.text_color}),
        encoding="utf-8",
    )
    logger.info(f"Banner colors saved: bg={colors.bg_color} text={colors.text_color}")
    return {"bg_color": colors.bg_color, "text_color": colors.text_color, "customized": True}


@router.delete("/settings/banner-colors", status_code=204)
async def reset_banner_colors() -> None:
    """Volta às cores padrão do banner (vermelho/branco)."""
    path = _banner_colors_file()
    if path.exists():
        path.unlink()
        logger.info("Banner colors reset to default")


# ─── Estilo da faixa divisória (modo streamer) ────────────────────────────────


def _bar_style_file():
    return settings.branding_dir / "bar_style.json"


class BarStyle(BaseModel):
    bg_color: str
    text_color: str
    font: str

    @field_validator("bg_color", "text_color")
    @classmethod
    def _valid_hex(cls, v: str) -> str:
        v = v.strip()
        if not _HEX_RE.match(v):
            raise ValueError("Cor inválida: use hexadecimal no formato #RRGGBB (ex: #101014)")
        return _normalize_hex(v)

    @field_validator("font")
    @classmethod
    def _known_font(cls, v: str) -> str:
        v = v.strip()
        if v not in BAR_FONTS:
            raise ValueError(f"Fonte desconhecida: escolha uma de {', '.join(BAR_FONTS)}")
        return v


def _bar_style_payload(bg: str, text: str, font: str, customized: bool) -> dict:
    return {
        "bg_color": bg,
        "text_color": text,
        "font": font,
        "customized": customized,
        # A lista vai junto porque depende das fontes instaladas na máquina —
        # o frontend não tem como saber quais existem.
        "available_fonts": available_bar_fonts(),
    }


@router.get("/settings/bar-style")
async def get_bar_style() -> dict:
    """Cor de fundo, cor do texto e fonte da faixa com o nome do streamer."""
    bg, text, font, customized = load_bar_style()
    return _bar_style_payload(bg, text, font, customized)


@router.put("/settings/bar-style")
async def set_bar_style(style: BarStyle) -> dict:
    """Define fundo, cor do texto e família da fonte da faixa divisória."""
    settings.branding_dir.mkdir(parents=True, exist_ok=True)
    _bar_style_file().write_text(
        json.dumps({
            "bg_color": style.bg_color,
            "text_color": style.text_color,
            "font": style.font,
        }),
        encoding="utf-8",
    )
    logger.info(
        f"Bar style saved: bg={style.bg_color} text={style.text_color} font={style.font}"
    )
    return _bar_style_payload(style.bg_color, style.text_color, style.font, True)


@router.delete("/settings/bar-style", status_code=204)
async def reset_bar_style() -> None:
    """Volta ao estilo padrão da faixa (fundo escuro, texto cinza claro)."""
    path = _bar_style_file()
    if path.exists():
        path.unlink()
        logger.info("Bar style reset to default")
