"""
A prévia da tela de estilo não pode mentir sobre o clipe.

As regras e medidas ficam em Python, onde o render as usa, e em TypeScript, para a prévia
responder sem ir ao servidor. A cópia é o preço de responder na hora; divergir, não. Mesma
ideia de `test_frontend_e_backend_concordam` em test_layouts.py.
"""

import re
from pathlib import Path

import pytest

from app import clip_style
from app.services import clipper, layout, subtitler, title_card

_TS = Path(__file__).resolve().parents[2] / "frontend" / "src" / "lib" / "clipStyle.ts"
_FONTE = _TS.read_text(encoding="utf-8")


def _texto(nome: str) -> str:
    return re.search(rf'export const {nome} = "([^"]+)"', _FONTE).group(1)


def _medida(nome: str) -> float:
    return float(re.search(rf"\b{nome}: ([\d.]+)", _FONTE).group(1))


@pytest.mark.parametrize(
    "nome,valor",
    [
        ("DEFAULT_BRAND", clip_style.DEFAULT_BRAND),
        ("INK", clip_style.INK),
        ("OUTLINE", clip_style.OUTLINE),
        ("WHITE", clip_style.WHITE),
        ("DEFAULT_FONT_KEY", clip_style.DEFAULT_FONT),
    ],
)
def test_constantes_iguais(nome, valor):
    assert _texto(nome) == valor


def test_contraste_minimo_igual():
    assert float(re.search(r"export const MIN_CONTRAST = ([\d.]+)", _FONTE).group(1)) == clip_style.MIN_CONTRAST


def test_paleta_igual():
    bloco = re.search(r"export const PALETTE[^=]*= \{(.*?)\};", _FONTE, re.S).group(1)
    assert dict(re.findall(r'(\w+): "(#[0-9A-Fa-f]{6})"', bloco)) == clip_style.PALETTE


def test_padrao_igual():
    padrao = clip_style.ClipStyle()
    bloco = re.search(r"export function defaultStyle.*?\n\}", _FONTE, re.S).group(0)
    assert 'estilo: "caixa"' in bloco and padrao.legenda.estilo == "caixa"
    assert 'tamanho: "M"' in bloco and padrao.legenda.tamanho == "M"
    assert padrao.legenda.cor == padrao.marca == clip_style.DEFAULT_BRAND
    assert padrao.titulo.fundo == clip_style.INK
    assert padrao.titulo.texto == clip_style.WHITE


@pytest.mark.parametrize(
    "nome,valor",
    [
        ("titleX", title_card.TITLE_X),
        ("titleY", title_card.TITLE_Y),
        ("titleMaxRight", title_card.TITLE_MAX_RIGHT),
        ("titleSize", title_card.TITLE_SIZE),
        ("titleLineHeight", title_card.TITLE_LINE_HEIGHT),
        ("titlePadX", title_card.TITLE_PAD_X),
        ("titlePadY", title_card.TITLE_PAD_Y),
        ("handleSize", title_card.HANDLE_SIZE),
        ("handleGap", title_card.HANDLE_GAP),
        ("coverH", layout.COVER_H),
        ("bannerTitleSize", layout.BANNER_MAX_SIZE),
        ("bannerPadY", layout._BANNER_PAD_Y),
        ("barH", clipper.COVER_BAR_H),
        ("barTextFrac", layout._BAR_TEXT_FRAC),
        ("barTracking", layout._BAR_TEXT_TRACKING),
        ("barGap", layout._BAR_TEXT_GAP),
        ("boxPaddingX", subtitler.BOX_PADDING_X),
        ("boxRadius", subtitler.BOX_RADIUS),
        ("boxNeighborGap", subtitler.BOX_NEIGHBOR_GAP),
        ("captionSizeFullscreen", subtitler.caption_geometry("fullscreen").size),
        ("captionSizeCover", subtitler.caption_geometry("cover").size),
        ("captionOutlineFullscreen", subtitler.caption_geometry("fullscreen").outline),
        ("captionOutlineCover", subtitler.caption_geometry("cover").outline),
        ("captionY", subtitler.caption_geometry("fullscreen").center_y),
    ],
)
def test_medidas_iguais(nome, valor):
    assert _medida(nome) == valor


def test_escala_da_previa_da_405x720():
    assert _medida("canvasW") * _medida("previewScale") == 405
    assert _medida("canvasH") * _medida("previewScale") == 720


def test_fatores_de_tamanho_iguais():
    bloco = re.search(r"SIZE_FACTORS[^=]*= \{(.*?)\}", _FONTE).group(1)
    fatores = {k: float(v) for k, v in re.findall(r"(\w): ([\d.]+)", bloco)}
    assert fatores == subtitler._SIZE_FACTORS


@pytest.mark.parametrize(
    "frase_ts",
    ["ilegível: escolha", "ilegível sobre esse fundo", "ilegível sobre o fundo do título"],
)
def test_as_regras_de_contraste_existem_na_tela(frase_ts):
    assert frase_ts in _FONTE


@pytest.mark.parametrize(
    "nome,valor",
    [
        ("CAPTION_Y_DEFAULT", clip_style.CAPTION_Y_DEFAULT),
        ("CAPTION_Y_MIN", clip_style.CAPTION_Y_MIN),
        ("CAPTION_Y_MAX", clip_style.CAPTION_Y_MAX),
    ],
)
def test_limites_da_altura_da_legenda_iguais(nome, valor):
    assert int(re.search(rf"export const {nome} = (\d+)", _FONTE).group(1)) == valor


def test_altura_padrao_e_a_de_sempre():
    assert clip_style.CAPTION_Y_DEFAULT == subtitler.caption_geometry("fullscreen").center_y


@pytest.mark.parametrize(
    "nome,valor",
    [
        ("WATERMARK_MIN_WIDTH", clip_style.WATERMARK_MIN_WIDTH),
        ("WATERMARK_MAX_WIDTH", clip_style.WATERMARK_MAX_WIDTH),
        ("WATERMARK_MIN_OPACITY", clip_style.WATERMARK_MIN_OPACITY),
    ],
)
def test_limites_da_marca_dagua_iguais(nome, valor):
    assert float(re.search(rf"export const {nome} = ([\d.]+)", _FONTE).group(1)) == valor


def test_layouts_da_marca_dagua_iguais():
    bloco = re.search(r"export const WATERMARK_LAYOUTS = \[(.*?)\]", _FONTE).group(1)
    assert tuple(re.findall(r'"(\w+)"', bloco)) == clip_style.WATERMARK_LAYOUTS


def test_padrao_da_marca_dagua_igual():
    bloco = re.search(r"export function defaultWatermark.*?\n\}", _FONTE, re.S).group(0)
    fora = clip_style.WatermarkPlacement()
    assert f"x: {fora.x}, y: {fora.y}" in bloco
