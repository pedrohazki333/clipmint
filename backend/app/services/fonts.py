"""
Qual arquivo de fonte cada parte do clipe usa.

O título, a legenda e o @ têm papéis diferentes, e na Archivo cada um é um arquivo
próprio (ver `scripts/gerar_fontes_archivo.py`). Uma fonte escolhida no perfil que não
esteja instalada nesta máquina cai na Archivo, que sempre existe: o FontField só
oferece o que está instalado, mas um job pode ser retomado em outra máquina.
"""

import logging
import shutil
from functools import lru_cache
from pathlib import Path
from typing import Literal

from PIL import ImageFont

from app.services.branding import _FONT_ASSETS_DIR, fonts_dir
from app.services.layout import BAR_FONTS, _first_existing

logger = logging.getLogger(__name__)

Role = Literal["titulo", "legenda", "arroba"]

_ARCHIVO: dict[str, str] = {
    "titulo": "ArchivoClipMintTitulo.ttf",
    "legenda": "ArchivoClipMintLegenda.ttf",
    "arroba": "ArchivoClipMintArroba.ttf",
}


def _archivo(role: Role) -> Path:
    instalada = fonts_dir() / _ARCHIVO[role]
    return instalada if instalada.exists() else _FONT_ASSETS_DIR / _ARCHIVO[role]


def font_path(font_key: str, role: Role) -> Path:
    """O arquivo da fonte deste papel, nesta máquina."""
    if font_key in BAR_FONTS:
        achada = _first_existing(BAR_FONTS[font_key][1])
        if achada:
            return Path(achada)
        logger.warning(f"Fonte {font_key!r} não está instalada aqui: usando a Archivo")
    return _archivo(role)


@lru_cache(maxsize=32)
def _load(path: str, size: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(path, size)


def load_font(font_key: str, role: Role, size: int) -> ImageFont.FreeTypeFont:
    return _load(str(font_path(font_key, role)), size)


def font_family(path: Path) -> str:
    """O nome de família, que é como o ASS pede a fonte."""
    return _load(str(path), 16).getname()[0]


def install_for_render(font_key: str, role: Role, clip_dir: Path) -> tuple[str, Path]:
    """
    Põe a fonte numa pasta só dela e devolve (família, pasta) para o filtro `ass`.

    Pasta própria porque o libass carrega TODOS os arquivos do `fontsdir`: apontar
    para a pasta de fontes do sistema leria centenas de arquivos, em memória, a cada
    render.
    """
    origem = font_path(font_key, role)
    pasta = clip_dir / "fonts"
    pasta.mkdir(parents=True, exist_ok=True)
    destino = pasta / origem.name
    if not destino.exists():
        shutil.copy2(origem, destino)
    return font_family(origem), pasta
