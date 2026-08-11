import io
import json
import logging
import re

from typing import Literal

from fastapi import APIRouter, File, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse
from PIL import Image, UnidentifiedImageError
from pydantic import BaseModel, field_validator

from app.services.branding import (
    BANNER_COLORS_FILE,
    BAR_STYLE_FILE,
    WATERMARK_FILE,
    branding_dir,
    preset_path,
)
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

# Cada conta tem os seus presets. O nicho é obrigatório em toda rota: com
# default, um esquecimento no frontend gravaria a marca de uma conta por cima
# da outra sem nenhum aviso.
SourceType = Literal["podcast", "gameplay", "siege"]
_SOURCE_QUERY = Query(..., description="Nicho dos presets: podcast ou gameplay")


def _watermark_file(source: str):
    return preset_path(source, WATERMARK_FILE)


@router.post("/settings/watermark", status_code=201)
async def upload_watermark(
    source: SourceType = _SOURCE_QUERY,
    file: UploadFile = File(...),
) -> dict:
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

    branding_dir(source)
    path = _watermark_file(source)
    img.save(path, format="PNG")
    logger.info(f"Watermark saved [{source}]: {path} ({img.width}x{img.height})")

    return {"status": "ok", "width": img.width, "height": img.height}


@router.get("/settings/watermark")
async def get_watermark(source: SourceType = _SOURCE_QUERY) -> FileResponse:
    """Retorna a marca d'água atual (404 se não configurada)."""
    path = _watermark_file(source)
    if not path.exists():
        raise HTTPException(status_code=404, detail="Nenhuma marca d'água configurada")
    return FileResponse(str(path), media_type="image/png")


@router.delete("/settings/watermark", status_code=204)
async def delete_watermark(source: SourceType = _SOURCE_QUERY) -> None:
    """Remove a marca d'água configurada."""
    path = _watermark_file(source)
    if path.exists():
        path.unlink()
        logger.info(f"Watermark removed [{source}]")


# ─── Cores do banner ──────────────────────────────────────────────────────────

_HEX_RE = re.compile(r"^#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{6})$")


def _banner_colors_file(source: str):
    return preset_path(source, BANNER_COLORS_FILE)


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
async def get_banner_colors(source: SourceType = _SOURCE_QUERY) -> dict:
    """Cores atuais do banner (padrões se nada foi customizado)."""
    bg, text, customized = load_banner_colors(source)
    return {"bg_color": bg, "text_color": text, "customized": customized}


@router.put("/settings/banner-colors")
async def set_banner_colors(
    colors: BannerColors, source: SourceType = _SOURCE_QUERY
) -> dict:
    """Define as cores do banner (fundo da pílula e fonte) em hexadecimal."""
    _banner_colors_file(source).write_text(
        json.dumps({"bg_color": colors.bg_color, "text_color": colors.text_color}),
        encoding="utf-8",
    )
    logger.info(f"Banner colors saved [{source}]: bg={colors.bg_color} text={colors.text_color}")
    return {"bg_color": colors.bg_color, "text_color": colors.text_color, "customized": True}


@router.delete("/settings/banner-colors", status_code=204)
async def reset_banner_colors(source: SourceType = _SOURCE_QUERY) -> None:
    """Volta às cores padrão do banner (vermelho/branco)."""
    path = _banner_colors_file(source)
    if path.exists():
        path.unlink()
        logger.info(f"Banner colors reset [{source}]")


# ─── Estilo da faixa divisória (modo streamer) ────────────────────────────────


def _bar_style_file(source: str):
    return preset_path(source, BAR_STYLE_FILE)


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
async def get_bar_style(source: SourceType = _SOURCE_QUERY) -> dict:
    """Cor de fundo, cor do texto e fonte da faixa com o nome do streamer."""
    bg, text, font, customized = load_bar_style(source)
    return _bar_style_payload(bg, text, font, customized)


@router.put("/settings/bar-style")
async def set_bar_style(
    style: BarStyle, source: SourceType = _SOURCE_QUERY
) -> dict:
    """Define fundo, cor do texto e família da fonte da faixa divisória."""
    _bar_style_file(source).write_text(
        json.dumps({
            "bg_color": style.bg_color,
            "text_color": style.text_color,
            "font": style.font,
        }),
        encoding="utf-8",
    )
    logger.info(
        f"Bar style saved [{source}]: bg={style.bg_color} text={style.text_color} font={style.font}"
    )
    return _bar_style_payload(style.bg_color, style.text_color, style.font, True)


@router.delete("/settings/bar-style", status_code=204)
async def reset_bar_style(source: SourceType = _SOURCE_QUERY) -> None:
    """Volta ao estilo padrão da faixa (fundo escuro, texto cinza claro)."""
    path = _bar_style_file(source)
    if path.exists():
        path.unlink()
        logger.info(f"Bar style reset [{source}]")
