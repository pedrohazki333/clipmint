"""
O título do clipe desenhado por cima do vídeo, com a palavra-chave em destaque.

PNG e não ASS: o título é fixo durante o clipe inteiro e tem caixa por linha, então
uma imagem só, sobreposta uma vez, é o caminho mais barato e o de medidas mais exatas.

As medidas estão em `docs/LAYOUTS_V2.md`.
"""

import logging
import re
import unicodedata
from typing import NamedTuple, Optional

from PIL import Image, ImageDraw, ImageFilter

from app.clip_style import MIN_CONTRAST, ClipStyle, contrast_ratio
from app.services.fonts import load_font
from app.services.layout import _balanced_wrap, _split_emoji_runs, parse_hex_color
from app.services.safe_area import Rect, unsafe_areas

logger = logging.getLogger(__name__)

# ─── Layout A: medidas no quadro de 1080x1920 ─────────────────────────────────
TITLE_X, TITLE_Y = 53, 197
TITLE_MAX_RIGHT = 909
TITLE_SIZE = 72
TITLE_LINE_HEIGHT = 1.32
TITLE_PAD_X, TITLE_PAD_Y = 24, 8
HANDLE_SIZE = 32
HANDLE_GAP = 14
_HANDLE_COLOR = (255, 255, 255, 255)
_SHADOW_COLOR = (0, 0, 0, 170)
_SHADOW_OFFSET = 2
_SHADOW_BLUR = 3

# Um título que não coube em tantas linhas diminui em vez de crescer para baixo: mais
# que isso já cobre o rosto de quem fala.
_MAX_LINES = 3
_MIN_SIZE = 44
_SIZE_STEP = 4

_EDGE_PUNCTUATION = ".,;:!?…—–-\"'”’»«()[]"


class TitleOverlay(NamedTuple):
    """Onde a imagem entra no quadro, e o que há nela para conferir as áreas seguras."""

    x: int
    y: int
    rects: list[Rect]


def _plain(word: str) -> str:
    decomposed = unicodedata.normalize("NFKD", word.strip(_EDGE_PUNCTUATION).lower())
    return "".join(c for c in decomposed if not unicodedata.combining(c))


def clean_title(title: str) -> str:
    """Sem emoji, que a fonte do título não tem, e em caixa alta."""
    texto = "".join(run for run, emoji in _split_emoji_runs(title or "") if not emoji)
    return re.sub(r"\s+", " ", texto).strip().upper()


def wrap_title(words: list[str], font_key: str, size: int, max_width: int) -> Optional[list[str]]:
    """Linhas equilibradas, da menor quantidade que couber. None se não couber."""
    font = load_font(font_key, "titulo", size)
    for n_lines in range(1, _MAX_LINES + 1):
        linhas = _balanced_wrap(words, font, max_width, n_lines)
        if linhas:
            return linhas
    return None


def fit_title(title: str, font_key: str, size: int, max_width: int) -> tuple[list[str], int]:
    """As linhas e o tamanho em que o título cabe, diminuindo a fonte se precisar."""
    words = title.split()
    atual = size
    while atual >= _MIN_SIZE:
        linhas = wrap_title(words, font_key, atual, max_width)
        if linhas:
            return linhas, atual
        atual -= _SIZE_STEP
    # Uma palavra enorme num tamanho mínimo: melhor sair inteira do que sumir.
    return [" ".join(words)], _MIN_SIZE


def draw_words(
    draw: ImageDraw.ImageDraw,
    x: float,
    y: float,
    line: str,
    font,
    color: tuple,
    keyword: Optional[str],
    keyword_color: tuple,
) -> None:
    """Escreve a linha palavra a palavra, para a palavra-chave sair em outra cor."""
    alvo = _plain(keyword) if keyword else None
    espaco = font.getlength(" ")
    for word in line.split():
        cor = keyword_color if alvo and _plain(word) == alvo else color
        draw.text((x, y), word, font=font, fill=cor)
        x += font.getlength(word) + espaco


# ─── Layout B: a faixa do título ──────────────────────────────────────────────
BAND_W, BAND_H = 1080, 256
BAND_Y = 800
BAND_BORDER = 8
BAND_TITLE_SIZE = 67
BAND_LINE_HEIGHT = 1.12
BAND_HANDLE_SIZE = 29
BAND_HANDLE_COLOR = "#C9C9CF"
BAND_HANDLE_GAP = 12
# A faixa cruza a coluna da direita do TikTok (y de 800 a 1500), então o texto tem o
# mesmo limite do título do layout A.
BAND_TEXT_X = TITLE_X
BAND_TEXT_RIGHT = TITLE_MAX_RIGHT


class BandLayout(NamedTuple):
    lines: list[str]
    size: int
    top: int
    rects: list[Rect]


def _band_layout(title: str, handle: str, font_key: str) -> BandLayout:
    """
    Linhas, tamanho e posição do texto dentro da faixa, centrado na vertical.

    Medido em ganchos reais: 1 em 10 fica com 3 linhas a 67px, e isso não cabe junto com
    o @. O título diminui até caber, em vez de vazar da faixa.
    """
    livre = BAND_H - 2 * BAND_BORDER
    largura = BAND_TEXT_RIGHT - BAND_TEXT_X
    handle_h = 0
    if handle:
        asc, desc = load_font(font_key, "arroba", BAND_HANDLE_SIZE).getmetrics()
        handle_h = asc + desc + (BAND_HANDLE_GAP if title else 0)

    linhas: list[str] = []
    tamanho = BAND_TITLE_SIZE
    passo = round(tamanho * BAND_LINE_HEIGHT)
    if title:
        palavras = title.split()
        while True:
            linhas = wrap_title(palavras, font_key, tamanho, largura) or [title]
            passo = round(tamanho * BAND_LINE_HEIGHT)
            fonte = load_font(font_key, "titulo", tamanho)
            cabe = passo * len(linhas) + handle_h <= livre and all(
                fonte.getlength(linha) <= largura for linha in linhas
            )
            if cabe or tamanho <= _MIN_SIZE:
                break
            tamanho -= _SIZE_STEP

    altura = passo * len(linhas) + handle_h
    topo = BAND_BORDER + (livre - altura) // 2

    rects: list[Rect] = []
    fonte = load_font(font_key, "titulo", tamanho)
    for indice, linha in enumerate(linhas):
        rects.append(Rect(BAND_TEXT_X, BAND_Y + topo + passo * indice, fonte.getlength(linha), passo))
    if handle:
        fonte_h = load_font(font_key, "arroba", BAND_HANDLE_SIZE)
        rects.append(
            Rect(BAND_TEXT_X, BAND_Y + topo + passo * len(linhas) + (BAND_HANDLE_GAP if title else 0),
                 fonte_h.getlength(handle), sum(fonte_h.getmetrics()))
        )
    return BandLayout(linhas, tamanho, topo, rects)


def band_handle_color(style: ClipStyle) -> str:
    """O cinza da especificação, salvo onde ele não se lê: aí vale a cor do texto."""
    if contrast_ratio(BAND_HANDLE_COLOR, style.titulo.fundo) >= MIN_CONTRAST:
        return BAND_HANDLE_COLOR
    return style.titulo.texto


def generate_cover_band(
    title: str,
    keyword: Optional[str],
    style: ClipStyle,
    output_path: str,
) -> BandLayout:
    """
    A faixa do layout B: fundo do estilo, borda na cor da marca, título e @ uma vez só.

    Sempre existe, mesmo com título e @ desligados: a geometria do layout não muda
    conforme o texto, e a faixa continua separando a capa de quem fala.
    """
    texto = clean_title(title) if style.titulo.ligado else ""
    handle = style.arroba.texto if style.arroba.ligado else ""
    fundo = parse_hex_color(style.titulo.fundo, (11, 11, 12, 255))
    marca = parse_hex_color(style.marca, (253, 55, 92, 255))
    cor_texto = parse_hex_color(style.titulo.texto, (255, 255, 255, 255))
    cor_handle = parse_hex_color(band_handle_color(style), (201, 201, 207, 255))

    plano = _band_layout(texto, handle, style.fonte)

    faixa = Image.new("RGBA", (BAND_W, BAND_H), fundo)
    desenho = ImageDraw.Draw(faixa)
    desenho.rectangle((0, 0, BAND_W - 1, BAND_BORDER - 1), fill=marca)
    desenho.rectangle((0, BAND_H - BAND_BORDER, BAND_W - 1, BAND_H - 1), fill=marca)

    fonte = load_font(style.fonte, "titulo", plano.size)
    passo = round(plano.size * BAND_LINE_HEIGHT)
    for indice, linha in enumerate(plano.lines):
        draw_words(
            desenho, BAND_TEXT_X, plano.top + passo * indice, linha, fonte, cor_texto, keyword, marca
        )
    if handle:
        y = plano.top + passo * len(plano.lines) + (BAND_HANDLE_GAP if texto else 0)
        desenho.text(
            (BAND_TEXT_X, y), handle, font=load_font(style.fonte, "arroba", BAND_HANDLE_SIZE), fill=cor_handle
        )

    faixa.convert("RGB").save(output_path)
    for rect in plano.rects:
        invadidas = unsafe_areas(rect)
        if invadidas:
            logger.warning(f"Faixa em área insegura ({', '.join(invadidas)}): {rect}")
    return plano


def generate_fullscreen_title(
    title: str,
    keyword: Optional[str],
    style: ClipStyle,
    output_path: str,
) -> Optional[TitleOverlay]:
    """
    Título e @ do layout A, numa imagem com fundo transparente.

    Cada linha tem a própria caixa, com a largura do próprio texto. Devolve None
    quando não há nada a desenhar, e o render simplesmente não sobrepõe imagem.
    """
    texto = clean_title(title) if style.titulo.ligado else ""
    handle = style.arroba.texto if style.arroba.ligado else ""
    if not texto and not handle:
        return None

    fundo = parse_hex_color(style.titulo.fundo, (11, 11, 12, 255))
    cor_texto = parse_hex_color(style.titulo.texto, (255, 255, 255, 255))
    cor_marca = parse_hex_color(style.marca, (253, 55, 92, 255))

    largura_max = TITLE_MAX_RIGHT - TITLE_X
    linhas: list[str] = []
    tamanho = TITLE_SIZE
    if texto:
        linhas, tamanho = fit_title(
            texto, style.fonte, TITLE_SIZE, largura_max - 2 * TITLE_PAD_X
        )
    fonte = load_font(style.fonte, "titulo", tamanho)
    ascent, descent = fonte.getmetrics()
    altura_caixa = ascent + descent + 2 * TITLE_PAD_Y
    passo = round(tamanho * TITLE_LINE_HEIGHT)

    # Altura do que vai ser desenhado, para a tela não ser maior do que precisa.
    altura_titulo = (passo * (len(linhas) - 1) + altura_caixa) if linhas else 0
    fonte_handle = load_font(style.fonte, "arroba", HANDLE_SIZE)
    asc_h, desc_h = fonte_handle.getmetrics()
    y_handle = altura_titulo + HANDLE_GAP if linhas else 0
    altura = (y_handle + asc_h + desc_h + _SHADOW_BLUR * 2) if handle else altura_titulo

    tela = Image.new("RGBA", (largura_max, altura), (0, 0, 0, 0))
    rects: list[Rect] = []

    if handle:
        sombra = Image.new("RGBA", tela.size, (0, 0, 0, 0))
        ImageDraw.Draw(sombra).text(
            (_SHADOW_OFFSET, y_handle + _SHADOW_OFFSET),
            handle,
            font=fonte_handle,
            fill=_SHADOW_COLOR,
        )
        tela.alpha_composite(sombra.filter(ImageFilter.GaussianBlur(_SHADOW_BLUR)))
        ImageDraw.Draw(tela).text((0, y_handle), handle, font=fonte_handle, fill=_HANDLE_COLOR)
        rects.append(
            Rect(
                TITLE_X,
                TITLE_Y + y_handle,
                fonte_handle.getlength(handle),
                asc_h + desc_h,
            )
        )

    desenho = ImageDraw.Draw(tela)
    for indice, linha in enumerate(linhas):
        y = passo * indice
        largura = fonte.getlength(linha) + 2 * TITLE_PAD_X
        desenho.rectangle((0, y, largura - 1, y + altura_caixa - 1), fill=fundo)
        draw_words(
            desenho, TITLE_PAD_X, y + TITLE_PAD_Y, linha, fonte, cor_texto, keyword, cor_marca
        )
        rects.append(Rect(TITLE_X, TITLE_Y + y, largura, altura_caixa))

    tela.save(output_path)

    for rect in rects:
        invadidas = unsafe_areas(rect)
        if invadidas:
            logger.warning(f"Título em área insegura ({', '.join(invadidas)}): {rect}")

    return TitleOverlay(TITLE_X, TITLE_Y, rects)
