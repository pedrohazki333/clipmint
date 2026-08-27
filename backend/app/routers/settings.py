import io
import json
import logging
import re


from pathlib import Path
from typing import Annotated, Optional

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse
from PIL import Image, UnidentifiedImageError
from pydantic import BaseModel, field_validator

from app.database import get_db
from app.deps import current_user
from app.features import SourceTypeField
from app.models import Profile, User
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.branding import (
    ensure_profile_dir,
    BANNER_COLORS_FILE,
    BAR_STYLE_FILE,
    CLIP_WATERMARK_FILE,
    WATERMARK_FILE,
    branding_dir,
    preset_path,
)
from app.services.layout import (
    BANNER_DEFAULT_FONT,
    BAR_DEFAULT_BG_HEX,
    BAR_DEFAULT_FONT,
    BAR_DEFAULT_TEXT_HEX,
    BAR_FONTS,
    available_bar_fonts,
    load_banner_style,
    load_bar_style,
)

# O nome escrito na faixa é um @ de conta, não um texto livre: um parágrafo ali
# viraria uma linha ilegível repetida na tela.
_MAX_BAR_NAME = 40


def _known_font(v: str) -> str:
    v = v.strip()
    if v not in BAR_FONTS:
        raise ValueError(f"Fonte desconhecida: escolha uma de {', '.join(BAR_FONTS)}")
    return v

logger = logging.getLogger(__name__)

# Duas escalas de preset, e a diferença é quem pode escrever:
#
#   - **do PERFIL** (`profile_id`): é seu. Qualquer usuário mexe nos presets dos
#     próprios perfis, e é isso que permite dois perfis da mesma rubrica terem
#     marcas diferentes.
#   - **do NICHO** (sem `profile_id`): compartilhado por toda a instalação, e
#     por isso restrito a quem administra. Ele é o padrão de quem ainda não subiu
#     marca própria.
#
# Era a dívida D42: antes só existia a escala do nicho, então no build público
# nenhum usuário comum conseguia pôr a própria marca nos clipes.
router = APIRouter(tags=["settings"])

_MAX_UPLOAD_BYTES = 5 * 1024 * 1024
_MAX_DIMENSION = 1024

# Cada conta tem os seus presets. O nicho é obrigatório em toda rota: com
# default, um esquecimento no frontend gravaria a marca de uma conta por cima
# da outra sem nenhum aviso. Quais nichos existem depende do build, então a
# validação é em tempo de request (ver app/features.py) — um Literal seria
# fixado no import e não teria como encolher no público.
# O Query fica DENTRO do Annotated: passado como valor default
# (`source: SourceType = Query(...)`), o FastAPI 0.115 descarta a validação que
# vem no Annotated e o nicho inválido passaria batido.
SourceType = Annotated[
    SourceTypeField,
    Query(description="Nicho dos presets (ex.: podcast, gameplay)"),
]


ProfileId = Annotated[
    Optional[str],
    Query(description="Perfil dono destes presets. Ausente = presets do nicho."),
]


async def _escopo_leitura(
    profile_id: ProfileId = None,
    user: User = Depends(current_user),
    db: AsyncSession = Depends(get_db),
) -> Optional[str]:
    """
    A escala para LER, validada.

    Com perfil: tem que ser um perfil DESTE usuário (404 se não for — nunca 403,
    ver D40). Sem perfil: é a escala compartilhada, e ler dali não é privilégio
    de ninguém — no build público ela nem devolve a marca de outra pessoa, cai
    na do produto (ver `preset_path`).

    Ler precisa passar para quem não administra porque a tela de CRIAR perfil
    ainda não tem um id para pedir: sem isto ela abriria sem a lista de fontes
    do servidor, mostrando só a padrão.
    """
    if profile_id:
        existe = (
            await db.execute(
                select(Profile.id).where(
                    Profile.id == profile_id, Profile.user_id == user.id
                )
            )
        ).scalar_one_or_none()
        if not existe:
            raise HTTPException(status_code=404, detail="Perfil não encontrado")
        return profile_id
    return None


async def _escopo(
    profile_id: Optional[str] = Depends(_escopo_leitura),
    user: User = Depends(current_user),
) -> Optional[str]:
    """
    A escala para ESCREVER.

    Mesma validação da leitura, mais a trava do nicho: aquela pasta é da
    instalação inteira, e deixar qualquer um gravar ali faria a marca de um
    aparecer no clipe do outro.
    """
    if profile_id is None and not user.is_owner:
        raise HTTPException(
            status_code=403,
            detail=(
                "Estes presets são da instalação inteira. Para ter a sua marca, "
                "configure-a dentro de um perfil seu."
            ),
        )
    return profile_id


Escopo = Annotated[Optional[str], Depends(_escopo)]
#: Para as rotas de leitura: valida o perfil, mas não exige ser dono.
EscopoLeitura = Annotated[Optional[str], Depends(_escopo_leitura)]


def _destino(source: str, filename: str, profile_id: Optional[str]) -> Path:
    """Onde ESCREVER este preset.

    Diferente de `preset_path`, que é onde LER: a leitura cai no nicho quando o
    perfil não tem o arquivo; a escrita nunca cai — senão gravar a marca de um
    perfil sobrescreveria a do nicho, que é de todo mundo.
    """
    if profile_id:
        return ensure_profile_dir(profile_id) / filename
    return preset_path(source, filename)


def _watermark_file(source: str, profile_id: Optional[str] = None):
    return preset_path(source, WATERMARK_FILE, profile_id)


def _clip_watermark_file(source: str, profile_id: Optional[str] = None):
    return preset_path(source, CLIP_WATERMARK_FILE, profile_id)


async def _store_upload(
    file: UploadFile, source: str, filename: str, escopo: Optional[str] = None
) -> dict:
    """
    Valida a imagem enviada, normaliza para PNG RGBA e grava no preset pedido.

    RGBA sempre, mesmo vindo de um JPEG: a marca do clipe é sobreposta ao vídeo,
    e sem canal alfa o recorte da arte viraria um retângulo de fundo.
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

    path = _destino(source, filename, escopo)
    path.parent.mkdir(parents=True, exist_ok=True)
    img.save(path, format="PNG")
    logger.info(f"{filename} saved [{source}]: {path} ({img.width}x{img.height})")

    return {"status": "ok", "width": img.width, "height": img.height}


@router.post("/settings/watermark", status_code=201)
async def upload_watermark(
    source: SourceType,
    escopo: Escopo = None,
    file: UploadFile = File(...),
) -> dict:
    """
    Recebe a logo/marca d'água do usuário (PNG/JPEG/WebP), normaliza para
    PNG RGBA (transparência preservada) e salva em storage/branding/.
    """
    return await _store_upload(file, source, WATERMARK_FILE, escopo)


@router.get("/settings/watermark")
async def get_watermark(source: SourceType, escopo: EscopoLeitura = None) -> FileResponse:
    """Retorna a marca d'água atual (404 se não configurada)."""
    path = _watermark_file(source, escopo)
    if not path.exists():
        raise HTTPException(status_code=404, detail="Nenhuma marca d'água configurada")
    return FileResponse(str(path), media_type="image/png")


@router.delete("/settings/watermark", status_code=204)
async def delete_watermark(source: SourceType, escopo: Escopo = None) -> None:
    """Remove a marca d'água configurada."""
    path = _watermark_file(source, escopo)
    if path.exists():
        path.unlink()
        logger.info(f"Watermark removed [{source}]")


# ─── Marca d'água do clipe ────────────────────────────────────────────────────


@router.post("/settings/clip-watermark", status_code=201)
async def upload_clip_watermark(
    source: SourceType,
    escopo: Escopo = None,
    file: UploadFile = File(...),
) -> dict:
    """Recebe a arte queimada no clipe inteiro (modo streamer)."""
    return await _store_upload(file, source, CLIP_WATERMARK_FILE, escopo)


@router.get("/settings/clip-watermark")
async def get_clip_watermark(source: SourceType, escopo: EscopoLeitura = None) -> FileResponse:
    """Retorna a arte atual (404 = esta conta não marca os clipes)."""
    path = _clip_watermark_file(source, escopo)
    if not path.exists():
        raise HTTPException(status_code=404, detail="Nenhuma marca d'água de clipe")
    return FileResponse(str(path), media_type="image/png")


@router.delete("/settings/clip-watermark", status_code=204)
async def delete_clip_watermark(source: SourceType, escopo: Escopo = None) -> None:
    """Remove a arte — os próximos clipes desta conta saem sem marca."""
    path = _clip_watermark_file(source, escopo)
    if path.exists():
        path.unlink()
        logger.info(f"Clip watermark removed [{source}]")


# ─── Cores do banner ──────────────────────────────────────────────────────────

_HEX_RE = re.compile(r"^#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{6})$")


def _banner_colors_file(source: str, escopo: Optional[str] = None):
    """Onde LER: o do perfil, se houver; senão o do nicho."""
    return preset_path(source, BANNER_COLORS_FILE, escopo)


def _normalize_hex(value: str) -> str:
    v = value.lstrip("#")
    if len(v) == 3:
        v = "".join(c * 2 for c in v)
    return f"#{v.upper()}"


class BannerColors(BaseModel):
    bg_color: str
    text_color: str
    # Opcional para não quebrar quem já chama a rota só com as cores: sem ela,
    # o banner fica na família padrão.
    font: str = BANNER_DEFAULT_FONT

    @field_validator("bg_color", "text_color")
    @classmethod
    def _valid_hex(cls, v: str) -> str:
        v = v.strip()
        if not _HEX_RE.match(v):
            raise ValueError("Cor inválida: use hexadecimal no formato #RRGGBB (ex: #ED2828)")
        return _normalize_hex(v)

    @field_validator("font")
    @classmethod
    def _valid_font(cls, v: str) -> str:
        return _known_font(v)


def _banner_payload(bg: str, text: str, font: str, customized: bool) -> dict:
    return {
        "bg_color": bg,
        "text_color": text,
        "font": font,
        "customized": customized,
        # Como na faixa: quais famílias existem depende da máquina do backend.
        "available_fonts": available_bar_fonts(),
    }


@router.get("/settings/banner-colors")
async def get_banner_colors(source: SourceType, escopo: EscopoLeitura = None) -> dict:
    """Cores e fonte atuais do banner (padrões se nada foi customizado)."""
    style = load_banner_style(source, escopo)
    return _banner_payload(style.bg_color, style.text_color, style.font, style.customized)


@router.put("/settings/banner-colors")
async def set_banner_colors(
    colors: BannerColors, source: SourceType, escopo: Escopo = None
) -> dict:
    """Define as cores do banner (fundo e texto) e a família da fonte."""
    # `_destino`, não `_banner_colors_file`: aquele cai no nicho quando o perfil
    # não tem o arquivo, e gravar por ali sobrescreveria a marca da instalação
    # inteira ao salvar a de um perfil.
    _destino(source, BANNER_COLORS_FILE, escopo).write_text(
        json.dumps({
            "bg_color": colors.bg_color,
            "text_color": colors.text_color,
            "font": colors.font,
        }),
        encoding="utf-8",
    )
    logger.info(
        f"Banner style saved [{source}]: bg={colors.bg_color} "
        f"text={colors.text_color} font={colors.font}"
    )
    return _banner_payload(colors.bg_color, colors.text_color, colors.font, True)


@router.delete("/settings/banner-colors", status_code=204)
async def reset_banner_colors(source: SourceType, escopo: Escopo = None) -> None:
    """Volta às cores padrão do banner (vermelho/branco)."""
    path = _banner_colors_file(source, escopo)
    if path.exists():
        path.unlink()
        logger.info(f"Banner colors reset [{source}]")


# ─── Estilo da faixa divisória (modo streamer) ────────────────────────────────


def _bar_style_file(source: str, escopo: Optional[str] = None):
    """Onde LER: o do perfil, se houver; senão o do nicho."""
    return preset_path(source, BAR_STYLE_FILE, escopo)


class BarStyle(BaseModel):
    bg_color: str
    text_color: str
    font: str
    # Vazio = a faixa cai no padrão (@suaconta) no modo streamer, e não aparece
    # no layout do podcast. Nunca no nome do canal do vídeo de origem.
    name: str = ""

    @field_validator("bg_color", "text_color")
    @classmethod
    def _valid_hex(cls, v: str) -> str:
        v = v.strip()
        if not _HEX_RE.match(v):
            raise ValueError("Cor inválida: use hexadecimal no formato #RRGGBB (ex: #101014)")
        return _normalize_hex(v)

    @field_validator("font")
    @classmethod
    def _valid_font(cls, v: str) -> str:
        return _known_font(v)

    @field_validator("name")
    @classmethod
    def _short_name(cls, v: str) -> str:
        v = v.strip()
        if len(v) > _MAX_BAR_NAME:
            raise ValueError(f"Nome muito longo (máx. {_MAX_BAR_NAME} caracteres)")
        return v


def _bar_style_payload(
    bg: str, text: str, font: str, name: str, customized: bool
) -> dict:
    return {
        "bg_color": bg,
        "text_color": text,
        "font": font,
        "name": name,
        "customized": customized,
        # A lista vai junto porque depende das fontes instaladas na máquina —
        # o frontend não tem como saber quais existem.
        "available_fonts": available_bar_fonts(),
    }


@router.get("/settings/bar-style")
async def get_bar_style(source: SourceType, escopo: EscopoLeitura = None) -> dict:
    """Cor de fundo, cor do texto, fonte e nome escrito na faixa."""
    style = load_bar_style(source, escopo)
    return _bar_style_payload(*style)


@router.put("/settings/bar-style")
async def set_bar_style(
    style: BarStyle, source: SourceType, escopo: Escopo = None
) -> dict:
    """Define fundo, cor do texto, família da fonte e nome da faixa divisória."""
    _destino(source, BAR_STYLE_FILE, escopo).write_text(
        json.dumps({
            "bg_color": style.bg_color,
            "text_color": style.text_color,
            "font": style.font,
            "name": style.name,
        }),
        encoding="utf-8",
    )
    logger.info(
        f"Bar style saved [{source}]: bg={style.bg_color} text={style.text_color} "
        f"font={style.font} name={style.name!r}"
    )
    return _bar_style_payload(
        style.bg_color, style.text_color, style.font, style.name, True
    )


@router.delete("/settings/bar-style", status_code=204)
async def reset_bar_style(source: SourceType, escopo: Escopo = None) -> None:
    """Volta ao estilo padrão da faixa (fundo escuro, texto cinza claro)."""
    path = _bar_style_file(source, escopo)
    if path.exists():
        path.unlink()
        logger.info(f"Bar style reset [{source}]")
