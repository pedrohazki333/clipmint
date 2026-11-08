"""
Qual arquivo de fonte cada parte do clipe usa.

O título, a legenda e o @ têm papéis diferentes, e na Archivo cada um é um arquivo
próprio (ver `scripts/gerar_fontes_archivo.py`). Uma fonte escolhida no perfil que não
esteja instalada nesta máquina cai na Archivo, que sempre existe: o FontField só
oferece o que está instalado, mas um job pode ser retomado em outra máquina.
"""

import logging
import shutil
import struct
from functools import lru_cache
from pathlib import Path
from typing import Literal, Optional

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


def _win_line_height(path: Path) -> Optional[float]:
    """(usWinAscent + usWinDescent) / unitsPerEm, lidos das tabelas do arquivo da fonte."""
    try:
        with open(path, "rb") as source:
            data = source.read(4096)
            num_tables = struct.unpack(">H", data[4:6])[0]
            tables: dict[bytes, int] = {}
            for index in range(num_tables):
                record = data[12 + index * 16:12 + (index + 1) * 16]
                tables[record[:4]] = struct.unpack(">I", record[8:12])[0]
            source.seek(tables[b"head"] + 18)
            units_per_em = struct.unpack(">H", source.read(2))[0]
            source.seek(tables[b"OS/2"] + 74)
            ascent, descent = struct.unpack(">HH", source.read(4))
    except (OSError, KeyError, struct.error, IndexError):
        return None
    if not units_per_em or not ascent + descent:
        return None
    return (ascent + descent) / units_per_em


def ass_font_size(path: Path, size: int) -> int:
    """
    O Fontsize do ASS que desenha letras de `size` pixels.

    O Fontsize do ASS não é o tamanho da letra: o libass escala a fonte para a altura de
    linha caber nele, e mede essa altura pelas métricas de Windows (`OS/2`), como o GDI.
    O Pillow mede pelas tipográficas. Na Archivo são 1,51 e 1,09, então pedir 88 desenhava
    letras de 58px, enquanto tudo que é medido com o Pillow esperava 88: a legenda saía
    pequena, com a caixa sobrando e as palavras afastadas. Medido no libass de verdade.
    """
    ratio = _win_line_height(path)
    if ratio is None:
        ascent, descent = _load(str(path), size).getmetrics()
        return ascent + descent
    return round(size * ratio)


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
