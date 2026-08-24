"""
Layout dos clips — capa estática + banner de título.

Formato final (1080x1920):
  ┌──────────────────┐
  │  CAPA (estática) │  ← print de uma expressão marcante do vídeo (0–768px)
  ├───── BANNER ─────┤  ← faixa vermelha com o título, sobre a emenda
  │  VÍDEO (rodando) │  ← crop com face tracking + legendas (768–1920px)
  └──────────────────┘

- Capa: MediaPipe escolhe o frame com a expressão mais forte (boca aberta =
  risada/espanto), com desempate por tamanho/confiança do rosto. Crop
  centralizado no rosto.
- Banner: faixa vermelha de largura cheia, cantos vivos, sem sombra, texto
  branco em caixa alta, quebra de linha e tamanho de fonte automáticos.
"""

import glob
import json
import logging
import math
import os
import re
import subprocess
import tempfile
from typing import Callable, NamedTuple, Optional

from PIL import Image, ImageDraw, ImageFont

from app.services.branding import (
    BANNER_COLORS_FILE,
    BAR_STYLE_FILE,
    preset_path,
)

logger = logging.getLogger(__name__)

CANVAS_W = 1080
COVER_W, COVER_H = 1080, 768

# ─── Geometria do modo streamer ───────────────────────────────────────────────

_BAR_BG = (16, 16, 20, 255)
_BAR_LOGO_FRAC = 0.62      # altura da logo em relação à altura da faixa

# Nome do streamer repetido ao longo da faixa. Discreto de propósito: a faixa é
# só a emenda entre os painéis, quem tem que puxar o olho é a cara e o jogo.
_BAR_TEXT_FRAC = 0.40      # tamanho da fonte em relação à altura da faixa
_BAR_TEXT_TRACKING = 0.18  # espaço entre letras, em frações do tamanho da fonte
_BAR_TEXT_GAP = 2.4        # espaço entre repetições, em múltiplos do tamanho da fonte
_BAR_TEXT_DOT = "•"
_BAR_DOT_MIX = 0.45        # ponto separador: fração da cor do texto (resto é fundo)
_BAR_HAIRLINE_MIX = 0.18   # fio de luz nas emendas, pela mesma mistura

BAR_DEFAULT_BG_HEX = "#101014"
# Este cinza é exatamente o que o branco a 60% de opacidade rendia sobre o fundo
# escuro. Virou o padrão para a cor escolhida valer o que aparece: sem alfa
# escondido, quem escolhe #FFFFFF recebe branco.
BAR_DEFAULT_TEXT_HEX = "#9D9D9F"
BAR_DEFAULT_FONT = "condensed"
# Nome escrito na faixa. Vazio = o layout decide: no streamer entra o nome do
# canal do vídeo; no 'cover' (podcast) não há faixa nenhuma, porque o que ela
# escreveria seria o canal alheio, e não a conta que publica o clipe.
BAR_DEFAULT_NAME = ""

# Famílias oferecidas para o nome na faixa: chave → (rótulo, arquivos em ordem
# de preferência). Só as que existem na máquina são oferecidas pela API.
BAR_FONTS: dict[str, tuple[str, list[str]]] = {
    "condensed": ("DejaVu Condensed", [
        "/usr/share/fonts/truetype/dejavu/DejaVuSansCondensed-Bold.ttf",
        "C:/Windows/Fonts/arialnb.ttf",
    ]),
    "sans": ("DejaVu Sans", [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "C:/Windows/Fonts/arialbd.ttf",
    ]),
    "inter": ("Inter", [
        "/usr/share/fonts/opentype/inter/Inter-Bold.otf",
        "/usr/share/fonts/truetype/inter/Inter-Bold.ttf",
    ]),
    "inter_black": ("Inter Black", [
        "/usr/share/fonts/opentype/inter/Inter-Black.otf",
        "/usr/share/fonts/truetype/inter/Inter-Black.ttf",
    ]),
    "montserrat": ("Montserrat", [
        "/usr/share/fonts/opentype/montserrat/Montserrat-Bold.otf",
        "/usr/share/fonts/truetype/montserrat/Montserrat-Bold.ttf",
    ]),
    "montserrat_black": ("Montserrat Black", [
        "/usr/share/fonts/opentype/montserrat/Montserrat-Black.otf",
        "/usr/share/fonts/truetype/montserrat/Montserrat-Black.ttf",
    ]),
    "serif": ("DejaVu Serif", [
        "/usr/share/fonts/truetype/dejavu/DejaVuSerif-Bold.ttf",
        "C:/Windows/Fonts/timesbd.ttf",
    ]),
    "mono": ("DejaVu Mono", [
        "/usr/share/fonts/truetype/dejavu/DejaVuSansMono-Bold.ttf",
        "C:/Windows/Fonts/consolab.ttf",
    ]),
}


class StreamerGeometry:
    """
    Painéis do layout streamer, em pixels do canvas final.

      ┌──────────────┐  0
      │   FACECAM    │
      ├──────────────┤  facecam_h
      │  faixa/logo  │
      ├──────────────┤  game_y
      │   GAMEPLAY   │
      └──────────────┘  canvas_h

    Alturas saem de frações do canvas (config), arredondadas para pares — o
    x264 em yuv420p exige dimensões pares em cada painel.
    """

    def __init__(self, width: int, facecam_frac: float, bar_frac: float):
        self.canvas_w = width - width % 2
        self.canvas_h = int(self.canvas_w * 16 / 9) // 2 * 2
        self.facecam_h = int(self.canvas_h * facecam_frac) // 2 * 2
        self.bar_h = int(self.canvas_h * bar_frac) // 2 * 2
        self.game_h = self.canvas_h - self.facecam_h - self.bar_h
        if self.game_h % 2:  # sobra ímpar volta para a faixa
            self.bar_h += 1
            self.game_h -= 1

    @property
    def game_y(self) -> int:
        return self.facecam_h + self.bar_h

    @property
    def facecam_aspect(self) -> float:
        return self.canvas_w / self.facecam_h

    @property
    def game_aspect(self) -> float:
        return self.canvas_w / self.game_h


def streamer_geometry() -> StreamerGeometry:
    from app.config import settings

    return StreamerGeometry(
        settings.streamer_output_width,
        settings.streamer_facecam_frac,
        settings.streamer_bar_frac,
    )


def _first_existing(paths: list[str]) -> Optional[str]:
    for path in paths:
        if os.path.exists(path):
            return path
    return None


def available_bar_fonts() -> list[dict]:
    """Famílias de fonte instaladas nesta máquina, para a API oferecer."""
    return [
        {"key": key, "label": label}
        for key, (label, paths) in BAR_FONTS.items()
        if _first_existing(paths)
    ]


class BarStyle(NamedTuple):
    """Estilo configurado da faixa. `name` é o texto repetido nela."""

    bg_color: str
    text_color: str
    font: str
    name: str
    customized: bool


def load_bar_style(source_type: Optional[str] = None) -> BarStyle:
    """
    Estilo configurado da faixa.

    Lê storage/branding/<nicho>/bar_style.json; sem arquivo (ou inválido),
    padrões. Cada conta guarda o seu estilo.
    """
    path = preset_path(source_type, BAR_STYLE_FILE)
    if path.exists():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            return BarStyle(
                data.get("bg_color") or BAR_DEFAULT_BG_HEX,
                data.get("text_color") or BAR_DEFAULT_TEXT_HEX,
                data.get("font") or BAR_DEFAULT_FONT,
                (data.get("name") or BAR_DEFAULT_NAME).strip(),
                True,
            )
        except (OSError, json.JSONDecodeError):
            logger.warning(f"Could not read {path}, using default bar style")
    return BarStyle(
        BAR_DEFAULT_BG_HEX, BAR_DEFAULT_TEXT_HEX, BAR_DEFAULT_FONT,
        BAR_DEFAULT_NAME, False,
    )


def _load_bar_font(font_key: str, size: int) -> ImageFont.FreeTypeFont:
    """Fonte da faixa; família desconhecida ou ausente cai na lista genérica."""
    label_paths = BAR_FONTS.get(font_key) or BAR_FONTS[BAR_DEFAULT_FONT]
    path = _first_existing(label_paths[1])
    if path:
        return ImageFont.truetype(path, size)
    logger.warning(f"Bar font {font_key!r} não encontrada — usando a fonte padrão")
    return _load_font(size)


def _mix(fg: tuple[int, int, int, int], bg: tuple[int, int, int, int], amount: float):
    """Mistura fg sobre bg (amount=1 mantém fg). Mantém tons proporcionais à
    cor escolhida, então detalhes discretos funcionam em faixa clara ou escura."""
    return tuple(int(b + (f - b) * amount) for f, b in zip(fg[:3], bg[:3])) + (255,)


def _tracked_width(text: str, font: ImageFont.FreeTypeFont, tracking: float) -> float:
    """Largura do texto com espaçamento extra entre as letras."""
    if not text:
        return 0.0
    return sum(font.getlength(c) for c in text) + tracking * (len(text) - 1)


def _draw_tracked(draw, x: float, y: float, text: str, font, fill, tracking: float) -> None:
    """Desenha letra a letra para conseguir o espaçamento (o PIL não tem tracking)."""
    for char in text:
        draw.text((x, y), char, font=font, fill=fill)
        x += font.getlength(char) + tracking


def _draw_repeating_name(
    bar: Image.Image, draw, name: str, height: int,
    font_key: str, text_rgba: tuple, dot_rgba: tuple,
) -> None:
    """
    Escreve o nome repetido ao longo de toda a faixa, com um ponto entre as
    repetições e o conjunto centralizado — as pontas saem cortadas de propósito,
    é o que faz a faixa parecer contínua em vez de uma legenda solta no meio.
    """
    size = max(8, int(height * _BAR_TEXT_FRAC))
    font = _load_bar_font(font_key, size)
    tracking = size * _BAR_TEXT_TRACKING

    name = _EMOJI_RE.sub("", name).strip().upper()
    if not name:
        return

    unit_w = _tracked_width(name, font, tracking)
    gap = size * _BAR_TEXT_GAP
    period = unit_w + gap
    repeats = int(bar.width // period) + 2
    total = repeats * period - gap
    x = (bar.width - total) / 2

    ascent, descent = font.getmetrics()
    y = (height - (ascent + descent)) / 2

    dot_w = font.getlength(_BAR_TEXT_DOT)
    for i in range(repeats):
        start = x + i * period
        _draw_tracked(draw, start, y, name, font, text_rgba, tracking)
        if i < repeats - 1:
            draw.text(
                (start + unit_w + (gap - dot_w) / 2, y),
                _BAR_TEXT_DOT, font=font, fill=dot_rgba,
            )


def generate_divider_bar(
    width: int,
    height: int,
    output_path: str,
    watermark_path: Optional[str] = None,
    text: Optional[str] = None,
    bg_color: Optional[str] = None,
    text_color: Optional[str] = None,
    font: Optional[str] = None,
    source_type: Optional[str] = None,
) -> str:
    """
    Faixa que separa a facecam do gameplay: barra com fios de luz nas duas
    emendas.

    Com `text` (nome do streamer), ele aparece repetido ao longo da faixa. Sem
    ele, a faixa leva a logo do usuário centralizada — o nome tem prioridade
    porque os dois juntos brigam pelo mesmo espaço.

    Cor de fundo, cor do texto e família da fonte vêm da configuração salva
    (storage/branding/bar_style.json) quando não são informadas. O ponto
    separador e os fios de luz são derivados das cores escolhidas, então a
    faixa continua legível tanto clara quanto escura.
    """
    if bg_color is None or text_color is None or font is None:
        stored = load_bar_style(source_type)
        bg_color = bg_color or stored.bg_color
        text_color = text_color or stored.text_color
        font = font or stored.font

    bg_rgba = parse_hex_color(bg_color, _BAR_BG)
    text_rgba = parse_hex_color(text_color, (255, 255, 255, 255))
    dot_rgba = _mix(text_rgba, bg_rgba, _BAR_DOT_MIX)
    hairline = _mix(text_rgba, bg_rgba, _BAR_HAIRLINE_MIX)

    bar = Image.new("RGBA", (width, height), bg_rgba)
    draw = ImageDraw.Draw(bar)
    draw.line([(0, 0), (width, 0)], fill=hairline)
    draw.line([(0, height - 1), (width, height - 1)], fill=hairline)

    if text and text.strip():
        _draw_repeating_name(bar, draw, text, height, font, text_rgba, dot_rgba)
        bar.save(output_path)
        logger.info(
            f"Divider bar generated: {output_path} ({width}x{height}, "
            f"name: {text!r}, font: {font}, bg: {bg_color}, text: {text_color})"
        )
        return output_path

    if watermark_path and os.path.exists(watermark_path):
        logo = Image.open(watermark_path).convert("RGBA")
        target_h = max(1, int(height * _BAR_LOGO_FRAC))
        target_w = max(1, int(logo.width * target_h / logo.height))
        if target_w > width:  # logo muito larga: limita pela largura da faixa
            target_w = width
            target_h = max(1, int(logo.height * target_w / logo.width))
        resized = logo.resize((target_w, target_h), Image.LANCZOS)
        bar.alpha_composite(resized, ((width - target_w) // 2, (height - target_h) // 2))

    bar.save(output_path)
    logger.info(
        f"Divider bar generated: {output_path} ({width}x{height}, "
        f"logo: {'yes' if watermark_path else 'no'})"
    )
    return output_path

# ─── Banner ───────────────────────────────────────────────────────────────────

_FONT_CANDIDATES = [
    # Windows
    "C:/Windows/Fonts/arialbd.ttf",       # Arial Bold
    "C:/Windows/Fonts/seguisb.ttf",       # Segoe UI Semibold
    "C:/Windows/Fonts/impact.ttf",
    # Linux
    "/usr/share/fonts/truetype/dejavu/DejaVuSansCondensed-Bold.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
]

_BANNER_RED = (237, 40, 40, 255)
_BANNER_TEXT_WHITE = (255, 255, 255, 255)
BANNER_DEFAULT_BG_HEX = "#ED2828"
BANNER_DEFAULT_TEXT_HEX = "#FFFFFF"
# A condensed é a que o banner sempre usou (DejaVuSansCondensed-Bold): mantê-la
# como padrão faz a fonte configurável não mudar nada em quem não escolheu.
BANNER_DEFAULT_FONT = "condensed"
_BANNER_MAX_TEXT_W = 840   # largura máxima de uma linha de texto
_BANNER_PAD_X = 60
_BANNER_PAD_Y = 34
_LINE_SPACING = 1.08

# Remove emojis/símbolos que a fonte não renderiza
_EMOJI_RE = re.compile(r"[\U0001F000-\U0001FAFF←-⯿️‍]")


_HEX_COLOR_RE = re.compile(r"^#?(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{6})$")


def parse_hex_color(value: Optional[str], fallback: tuple[int, int, int, int]) -> tuple[int, int, int, int]:
    """Converte '#RGB'/'#RRGGBB' em RGBA; hex inválido cai no fallback (nunca quebra o pipeline)."""
    if not value:
        return fallback
    value = value.strip()
    if not _HEX_COLOR_RE.match(value):
        logger.warning(f"Invalid banner hex color {value!r}, using default")
        return fallback
    v = value.lstrip("#")
    if len(v) == 3:
        v = "".join(c * 2 for c in v)
    return (int(v[0:2], 16), int(v[2:4], 16), int(v[4:6], 16), 255)


class BannerStyle(NamedTuple):
    """Estilo configurado do banner de título."""

    bg_color: str
    text_color: str
    font: str
    customized: bool


def load_banner_style(source_type: Optional[str] = None) -> BannerStyle:
    """
    Estilo configurado do banner (cores + família da fonte).

    Lê storage/branding/<nicho>/banner_colors.json; sem arquivo (ou inválido),
    padrões. Cada conta guarda o seu estilo.
    """
    path = preset_path(source_type, BANNER_COLORS_FILE)
    if path.exists():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            return BannerStyle(
                data.get("bg_color") or BANNER_DEFAULT_BG_HEX,
                data.get("text_color") or BANNER_DEFAULT_TEXT_HEX,
                data.get("font") or BANNER_DEFAULT_FONT,
                True,
            )
        except (OSError, json.JSONDecodeError):
            logger.warning(f"Could not read {path}, using default banner style")
    return BannerStyle(
        BANNER_DEFAULT_BG_HEX, BANNER_DEFAULT_TEXT_HEX, BANNER_DEFAULT_FONT, False,
    )


def _load_font(size: int) -> ImageFont.FreeTypeFont:
    for path in _FONT_CANDIDATES:
        if os.path.exists(path):
            return ImageFont.truetype(path, size)
    return ImageFont.load_default(size)


def _balanced_wrap(
    words: list[str],
    font: ImageFont.FreeTypeFont,
    max_w: int,
    n_lines: int,
    measure: Optional[Callable[[str], float]] = None,
) -> Optional[list[str]]:
    """
    Divide as palavras em exatamente n_lines com larguras equilibradas
    (minimiza a linha mais larga — bloco simétrico, sem linha órfã).
    None se não couber em max_w.

    `measure` existe para o texto que mistura fonte: um emoji não tem largura
    na fonte do texto, e medir a linha com `font.getlength` faria o banner com
    emoji parecer mais estreito do que é — e vazar da caixa.
    """
    from itertools import combinations

    measure = measure or font.getlength

    if n_lines == 1:
        line = " ".join(words)
        return [line] if measure(line) <= max_w else None

    if len(words) < n_lines:
        return None

    best: Optional[list[str]] = None
    best_width = float("inf")
    for splits in combinations(range(1, len(words)), n_lines - 1):
        bounds = [0, *splits, len(words)]
        lines = [" ".join(words[a:b]) for a, b in zip(bounds, bounds[1:])]
        widest = max(measure(l) for l in lines)
        if widest <= max_w and widest < best_width:
            best, best_width = lines, widest
    return best


def generate_banner(
    text: str,
    output_path: str,
    bg_color: Optional[str] = None,
    text_color: Optional[str] = None,
    font_key: Optional[str] = None,
    source_type: Optional[str] = None,
) -> tuple[int, int]:
    """
    Gera o PNG do retângulo com o título — largura cheia do canvas (1080px),
    cantos vivos, sem sombra.

    Cores em hex (#RGB/#RRGGBB) e família da fonte (chave de BAR_FONTS); None
    usa a configuração salva do nicho (banner_colors.json) ou os padrões.

    Returns:
        (width, height) da imagem gerada — usado para posicionar o overlay.
    """
    if bg_color is None or text_color is None or font_key is None:
        stored = load_banner_style(source_type)
        bg_color = bg_color or stored.bg_color
        text_color = text_color or stored.text_color
        font_key = font_key or stored.font

    box_rgba = parse_hex_color(bg_color, _BANNER_RED)
    text_rgba = parse_hex_color(text_color, _BANNER_TEXT_WHITE)

    text = _EMOJI_RE.sub("", text).strip().upper()
    if not text:
        text = "ASSISTA ATÉ O FINAL"

    # Preferência: até 2 linhas equilibradas com fonte grande;
    # 3 linhas só como último recurso para textos muito longos
    words = text.split()
    font, lines = None, None
    for max_lines in (2, 3):
        min_size = 44 if max_lines == 2 else 34
        for size in range(60, min_size - 1, -2):
            f = _load_bar_font(font_key, size)
            for n in range(1, max_lines + 1):
                wrapped = _balanced_wrap(words, f, _BANNER_MAX_TEXT_W, n)
                if wrapped:
                    font, lines = f, wrapped
                    break
            if font:
                break
        if font:
            break
    if font is None:  # texto extremamente longo: trunca
        font = _load_bar_font(font_key, 34)
        lines = _balanced_wrap(words[:14], font, _BANNER_MAX_TEXT_W, 3) or [text[:30]]

    ascent, descent = font.getmetrics()
    line_h = math.ceil((ascent + descent) * _LINE_SPACING)
    text_w = max(int(font.getlength(l)) for l in lines)
    text_h = line_h * len(lines)

    # Largura do canvas inteiro: o retângulo vai de borda a borda, e o texto
    # fica centralizado dentro dele (_BANNER_MAX_TEXT_W garante a folga lateral).
    # O max() é só uma trava — o texto nunca passa de 840px + padding.
    box_w = max(CANVAS_W, text_w + 2 * _BANNER_PAD_X)
    box_h = text_h + 2 * _BANNER_PAD_Y

    # Retângulo reto: cantos vivos e nada atrás dele. O lábio 3D que ficava sob
    # a pílula foi retirado a pedido do usuário (23/08/2026) — sem sombra.
    img = Image.new("RGBA", (box_w, box_h), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    draw.rectangle([0, 0, box_w - 1, box_h - 1], fill=box_rgba)

    y = _BANNER_PAD_Y + (line_h - ascent - descent) // 2
    for line in lines:
        x = (box_w - font.getlength(line)) / 2
        draw.text((x, y), line, font=font, fill=text_rgba)
        y += line_h

    img.save(output_path)
    logger.info(
        f"Banner generated: {output_path} ({box_w}x{box_h}, "
        f"{len(lines)} line(s), font: {font_key})"
    )
    return box_w, box_h


# ─── Banner de título do layout streamer ──────────────────────────────────────
#
# Outro banner, com outro trabalho. O de cima (generate_banner) fica na emenda
# do layout 'cover', tem a largura do texto e o texto em caixa alta.
# Este ocupa a largura inteira e encosta na faixa do streamer,
# formando um bloco só com ela — o que o usuário desenhou no exemplo enviado em
# 20/08/2026.
#
# A razão de ele existir é de retenção, não de estética: a legenda passa palavra
# a palavra e muitas vezes não chega a ser lida. Um título parado nos primeiros
# segundos é a única coisa na tela que diz do que se trata o clipe antes de a
# fala chegar lá.

# Margem lateral: o texto respira sem que a caixa deixe de ser de ponta a ponta.
_TITLE_PAD_X = 48
_TITLE_PAD_Y = 26
# Fonte: grande o bastante para ser lida de relance, e o suficiente para caber
# em duas linhas. Abaixo do mínimo o título compete com a legenda em vez de
# dominar, e aí não cumpre a função.
_TITLE_MAX_SIZE = 62
_TITLE_MIN_SIZE = 38
_TITLE_LINE_SPACING = 1.12
_TITLE_MAX_LINES = 2


# ─── Emoji colorido ───────────────────────────────────────────────────────────
#
# O emoji do hook faz parte do gancho ("Voltou minha casca no último segundo 😱")
# e o resto do sistema o descarta — o banner do layout 'cover' e a faixa tiram
# emoji do texto porque a fonte de texto simplesmente não tem esses glifos, e o
# que sairia é o retângulo de "caractere ausente".
#
# Desenhá-lo custa duas coisas que não são óbvias:
#
# 1. A NotoColorEmoji é uma fonte de BITMAP (CBDT) com um único tamanho de
#    strike: 109px. Pedir qualquer outro tamanho levanta "invalid pixel size".
#    Então o emoji é desenhado no tamanho nativo e reduzido para a altura da
#    linha — daí o LANCZOS, que é o que evita a borda serrilhada na redução.
# 2. Ele não pode ser desenhado junto com o texto: são fontes diferentes na
#    mesma linha. A linha é quebrada em trechos (texto | emoji) e cada um vai
#    com o seu desenho, somando as larguras para o alinhamento continuar certo.
#
# Sem a fonte instalada nada disso acontece e o emoji volta a ser removido —
# um clip sem emoji é melhor que um clip com tofu.

_EMOJI_NATIVE_SIZE = 109  # único strike da NotoColorEmoji

_EMOJI_FONT_SYSTEM_PATHS = [
    "/usr/share/fonts/truetype/noto/NotoColorEmoji.ttf",
    "/usr/share/fonts/opentype/noto/NotoColorEmoji.ttf",
    "/usr/local/share/fonts/NotoColorEmoji.ttf",
    os.path.expanduser("~/.local/share/fonts/NotoColorEmoji.ttf"),
    "C:/Windows/Fonts/seguiemj.ttf",  # Segoe UI Emoji
]

# Altura do emoji em relação ao ascent da fonte do texto, e o respiro lateral
# em relação à altura dele. Emoji na altura cheia do ascent fica maior que as
# maiúsculas ao lado e puxa o olho para longe da palavra.
_EMOJI_HEIGHT_FRAC = 0.86
_EMOJI_SIDE_FRAC = 0.10


def emoji_font_path() -> Optional[str]:
    """
    Caminho da fonte de emoji colorido, ou None se não houver nenhuma.

    A baixada pelo projeto (`make emoji-font`) vem primeiro: ela é a que se
    sabe qual é. Uma do sistema pode ser qualquer versão, mas serve.
    """
    from app.config import settings

    baixada = os.path.join(str(settings.branding_dir), "fonts", "NotoColorEmoji.ttf")
    return _first_existing([baixada, *_EMOJI_FONT_SYSTEM_PATHS])


def _split_emoji_runs(text: str) -> list[tuple[str, bool]]:
    """
    Quebra o texto em trechos (conteúdo, é_emoji), preservando a ordem.

    Emojis vizinhos entram num trecho só: uma sequência ZWJ (família, bandeira,
    tom de pele) é um glifo só depois do shaping, e separá-la em caracteres
    desenharia as partes soltas.
    """
    runs: list[tuple[str, bool]] = []
    for char in text:
        is_emoji = bool(_EMOJI_RE.match(char))
        if runs and runs[-1][1] == is_emoji:
            runs[-1] = (runs[-1][0] + char, is_emoji)
        else:
            runs.append((char, is_emoji))
    return [(content, flag) for content, flag in runs if content]


def _render_emoji(cluster: str, target_h: int) -> Optional[Image.Image]:
    """O emoji desenhado no tamanho nativo e reduzido para `target_h`."""
    path = emoji_font_path()
    if path is None or target_h <= 0:
        return None
    try:
        font = ImageFont.truetype(path, _EMOJI_NATIVE_SIZE)
    except OSError as exc:
        logger.warning(f"Fonte de emoji não pôde ser carregada ({exc})")
        return None

    ascent, descent = font.getmetrics()
    width = max(1, math.ceil(font.getlength(cluster)))
    canvas = Image.new("RGBA", (width, ascent + descent), (0, 0, 0, 0))
    try:
        ImageDraw.Draw(canvas).text((0, 0), cluster, font=font, embedded_color=True)
    except (OSError, ValueError) as exc:
        logger.warning(f"Emoji {cluster!r} não pôde ser desenhado ({exc})")
        return None

    box = canvas.getbbox()
    if not box:
        return None
    glyph = canvas.crop(box)
    scale = target_h / glyph.height
    return glyph.resize(
        (max(1, round(glyph.width * scale)), target_h), Image.LANCZOS
    )


def _emoji_metrics(font: ImageFont.FreeTypeFont) -> tuple[int, int]:
    """(altura do emoji, respiro lateral) para a fonte de texto dada."""
    ascent, _ = font.getmetrics()
    height = max(1, round(ascent * _EMOJI_HEIGHT_FRAC))
    return height, round(height * _EMOJI_SIDE_FRAC)


def _mixed_line_width(line: str, font: ImageFont.FreeTypeFont) -> float:
    """Largura de uma linha que mistura texto e emoji."""
    emoji_h, side = _emoji_metrics(font)
    total = 0.0
    for content, is_emoji in _split_emoji_runs(line):
        glyph = _render_emoji(content, emoji_h) if is_emoji else None
        if glyph is None:
            # Não é emoji, ou a fonte de emoji não tem este glifo. O intervalo
            # de _EMOJI_RE inclui setas e sinais que fontes de texto desenham
            # normalmente — devolvê-los ao texto é melhor que engoli-los.
            total += font.getlength(content)
        else:
            total += glyph.width + 2 * side
    return total


def _draw_mixed_line(
    img: Image.Image,
    draw: ImageDraw.ImageDraw,
    line: str,
    font: ImageFont.FreeTypeFont,
    x: float,
    y: float,
    fill: tuple,
) -> None:
    """Desenha a linha trecho a trecho, alternando a fonte do texto e o emoji."""
    ascent, _ = font.getmetrics()
    emoji_h, side = _emoji_metrics(font)

    for content, is_emoji in _split_emoji_runs(line):
        glyph = _render_emoji(content, emoji_h) if is_emoji else None
        if glyph is None:
            draw.text((x, y), content, font=font, fill=fill)
            x += font.getlength(content)
            continue
        # Assentado na linha de base do texto: alinhar pelo topo deixaria o
        # emoji flutuando acima das letras.
        img.alpha_composite(glyph, (round(x + side), round(y + ascent - emoji_h)))
        x += glyph.width + 2 * side


def generate_title_banner(
    text: str,
    output_path: str,
    canvas_w: int = CANVAS_W,
    bg_color: Optional[str] = None,
    text_color: Optional[str] = None,
    font_key: Optional[str] = None,
    source_type: Optional[str] = None,
) -> tuple[int, int]:
    """
    Gera o PNG retangular do título que encosta na faixa do streamer.

    Ao contrário do banner do layout 'cover', o texto NÃO vai para caixa alta:
    o exemplo aprovado usa caixa de frase, e em duas linhas longas a caixa alta
    engorda o suficiente para forçar uma fonte menor.

    Cores e fonte saem dos presets do nicho — as mesmas da faixa —, para o
    título e a faixa lerem como uma peça só em vez de dois adesivos colados.

    Returns:
        (width, height) do PNG gerado.
    """
    if bg_color is None or text_color is None:
        stored = load_banner_style(source_type)
        bg_color = bg_color or stored.bg_color
        text_color = text_color or stored.text_color
    if font_key is None:
        font_key = load_bar_style(source_type).font

    bg_rgba = parse_hex_color(bg_color, _BANNER_RED)
    text_rgba = parse_hex_color(text_color, _BANNER_TEXT_WHITE)

    # O emoji do hook é parte do gancho e fica — desde que haja fonte para
    # desenhá-lo. Sem ela sai o retângulo de caractere ausente, que é pior que
    # não ter emoji nenhum.
    if emoji_font_path() is None:
        text = _EMOJI_RE.sub("", text)
    text = text.strip()
    if not text:
        raise ValueError("Título do banner vazio")

    max_text_w = canvas_w - 2 * _TITLE_PAD_X
    words = text.split()

    font, lines = None, None
    for size in range(_TITLE_MAX_SIZE, _TITLE_MIN_SIZE - 1, -2):
        candidate = _load_bar_font(font_key, size)
        measure = lambda line, f=candidate: _mixed_line_width(line, f)
        for n in range(1, _TITLE_MAX_LINES + 1):
            wrapped = _balanced_wrap(words, candidate, max_text_w, n, measure)
            if wrapped:
                font, lines = candidate, wrapped
                break
        if font:
            break

    if font is None:
        # Título longo demais para duas linhas legíveis. Truncar é melhor que
        # encolher mais: um título que exige esforço para ler não retém
        # ninguém, e o texto completo continua no título do post.
        font = _load_bar_font(font_key, _TITLE_MIN_SIZE)
        measure = lambda line: _mixed_line_width(line, font)
        lines = None
        for keep in range(len(words) - 1, 2, -1):
            lines = _balanced_wrap(
                words[:keep], font, max_text_w, _TITLE_MAX_LINES, measure
            )
            if lines:
                lines[-1] = lines[-1] + "..."
                break
        if not lines:
            lines = [text[:24] + "..."]
        logger.info(f"Título do banner truncado para caber em {_TITLE_MAX_LINES} linhas")

    ascent, descent = font.getmetrics()
    line_h = math.ceil((ascent + descent) * _TITLE_LINE_SPACING)
    height = line_h * len(lines) + 2 * _TITLE_PAD_Y
    height = height // 2 * 2  # dimensão par: o overlay entra num canvas yuv420p

    img = Image.new("RGBA", (canvas_w, height), bg_rgba)
    draw = ImageDraw.Draw(img)

    y = _TITLE_PAD_Y + (line_h - ascent - descent) // 2
    for line in lines:
        x = (canvas_w - _mixed_line_width(line, font)) / 2
        _draw_mixed_line(img, draw, line, font, x, y, text_rgba)
        y += line_h

    img.save(output_path)
    logger.info(
        f"Title banner generated: {output_path} ({canvas_w}x{height}, "
        f"{len(lines)} linha(s), fonte {font.size}px)"
    )
    return canvas_w, height


def _smoothstep(p: float) -> float:
    """Aceleração suave nas duas pontas (3p² − 2p³), para p em [0,1]."""
    p = min(1.0, max(0.0, p))
    return p * p * (3.0 - 2.0 * p)


def generate_banner_collapse_frames(
    banner_path: str,
    output_dir: str,
    n_frames: int,
) -> list[str]:
    """
    Os quadros da saída do banner: ele encolhe para dentro da faixa.

    A borda de BAIXO fica presa na faixa e a de CIMA desce até encontrá-la,
    recortando o conteúdo — o texto não se move nem diminui, vai sendo comido
    de cima para baixo. Foi assim no exemplo aprovado, e é diferente de deslizar
    para trás da faixa (que comeria o texto de baixo para cima, movendo-o).

    Cada quadro tem o tamanho INTEIRO do banner, com a parte já recolhida
    transparente. Tamanho constante é o que permite entregá-los ao FFmpeg como
    uma sequência de imagens e sobrepô-los numa posição fixa: o `overlay` exige
    dimensões constantes, e o `crop` do FFmpeg não aceita altura variável no
    tempo. Recortar aqui, no Pillow, custa milissegundos e evita um filtergraph
    que o FFmpeg não sabe montar.

    Returns:
        Os caminhos dos quadros, em ordem. O último é totalmente transparente.
    """
    master = Image.open(banner_path).convert("RGBA")
    width, height = master.size
    os.makedirs(output_dir, exist_ok=True)

    paths: list[str] = []
    for i in range(n_frames):
        # i=0 já sai do repouso: o quadro idêntico ao estático seria um quadro
        # perdido no meio de uma animação de ~0,2s.
        collapsed = _smoothstep((i + 1) / n_frames)
        visible = int(round(height * (1.0 - collapsed)))

        frame = Image.new("RGBA", (width, height), (0, 0, 0, 0))
        if visible > 0:
            strip = master.crop((0, height - visible, width, height))
            frame.paste(strip, (0, height - visible))

        path = os.path.join(output_dir, f"collapse_{i:03d}.png")
        frame.save(path)
        paths.append(path)

    logger.info(f"Banner collapse: {n_frames} quadro(s) em {output_dir}")
    return paths


# ─── Capa (frame expressivo) ──────────────────────────────────────────────────

def _mouth_openness(image_rgb) -> float:
    """Razão de abertura da boca via FaceMesh (0 = fechada; >0.5 = bem aberta)."""
    import mediapipe as mp

    with mp.solutions.face_mesh.FaceMesh(
        static_image_mode=True, max_num_faces=1, min_detection_confidence=0.5
    ) as mesh:
        result = mesh.process(image_rgb)
    if not result.multi_face_landmarks:
        return 0.0
    lm = result.multi_face_landmarks[0].landmark
    # 13/14 = lábios internos (cima/baixo); 61/291 = cantos da boca
    vertical = math.dist((lm[13].x, lm[13].y), (lm[14].x, lm[14].y))
    horizontal = math.dist((lm[61].x, lm[61].y), (lm[291].x, lm[291].y))
    return vertical / horizontal if horizontal > 0 else 0.0


def generate_cover(
    video_path: str,
    start_time: float,
    end_time: float,
    output_path: str,
    width: int = COVER_W,
    height: int = COVER_H,
    watermark_path: Optional[str] = None,
    qr_regions: Optional[list[tuple[int, int, int, int]]] = None,
    static_regions: Optional[list[tuple[int, int, int, int]]] = None,
) -> str:
    """
    Captura o frame mais expressivo do trecho e recorta como capa.

    Estratégia: amostra 1 frame/s, detecta rostos (MediaPipe), pré-seleciona os
    8 melhores por confiança × tamanho e escolhe o de boca mais aberta
    (risada/espanto = expressão forte). Crop centralizado no rosto.

    Returns:
        "expressive" | "biggest_face" | "center" (método usado, para logging).
    """
    import cv2
    import mediapipe as mp

    duration = max(end_time - start_time, 1.0)

    with tempfile.TemporaryDirectory() as tmpdir:
        pattern = os.path.join(tmpdir, "c_%04d.jpg")
        subprocess.run(
            ["ffmpeg", "-y", "-ss", str(start_time), "-i", video_path,
             "-t", str(duration), "-vf", "fps=1", "-q:v", "2", pattern],
            capture_output=True, timeout=300,
        )
        frames = sorted(glob.glob(os.path.join(tmpdir, "c_*.jpg")))
        if not frames:
            raise RuntimeError(f"Could not extract cover frames from {video_path}")

        # Detecta rostos em todos os frames amostrados
        candidates = []  # (frame_path, cx, cy, area, det_score)
        with mp.solutions.face_detection.FaceDetection(
            model_selection=1, min_detection_confidence=0.5
        ) as detector:
            for path in frames:
                img = cv2.imread(path)
                if img is None:
                    continue
                res = detector.process(cv2.cvtColor(img, cv2.COLOR_BGR2RGB))
                if not res.detections:
                    continue
                best = max(res.detections, key=lambda d: d.score[0])
                b = best.location_data.relative_bounding_box
                candidates.append((
                    path,
                    min(1.0, max(0.0, b.xmin + b.width / 2)),
                    min(1.0, max(0.0, b.ymin + b.height / 2)),
                    max(0.0, b.width * b.height),
                    float(best.score[0]),
                ))

        method = "expressive"
        if not candidates:
            # Sem rosto: frame do meio, crop central
            chosen = (frames[len(frames) // 2], 0.5, 0.45, 0.0, 0.0)
            method = "center"
        else:
            # Top 8 por confiança × tamanho → mais expressivo (boca aberta)
            candidates.sort(key=lambda c: c[3] * c[4], reverse=True)
            top = candidates[:8]
            max_area = max(c[3] for c in top) or 1.0
            scored = []
            for cand in top:
                try:
                    img = cv2.imread(cand[0])
                    mar = _mouth_openness(cv2.cvtColor(img, cv2.COLOR_BGR2RGB))
                except Exception:
                    mar = 0.0
                scored.append((mar + 0.3 * (cand[3] / max_area), cand))
            scored.sort(key=lambda s: s[0], reverse=True)
            chosen = scored[0][1]
            if all(s[0] <= 0.3 for s in scored):
                method = "biggest_face"

        frame_path, cx, cy = chosen[0], chosen[1], chosen[2]
        crop_box = _crop_to_cover(frame_path, cx, cy, width, height, output_path)

    # Regiões de marcas de terceiros (coordenadas da fonte) → coordenadas da capa
    qr_in_cover = _transform_regions(qr_regions or [], crop_box, width, height)
    static_in_cover = _transform_regions(static_regions or [], crop_box, width, height)

    _brand_cover(output_path, watermark_path, qr_in_cover, static_in_cover)
    logger.info(f"Cover generated ({method}): {output_path}")
    return method


def _transform_regions(
    regions: list[tuple[int, int, int, int]],
    crop_box: tuple[int, int, int, int],
    out_w: int,
    out_h: int,
) -> list[tuple[int, int, int, int]]:
    """Converte regiões da fonte para coordenadas da capa (descarta as que
    ficam quase totalmente fora do crop)."""
    cx, cy, cw, ch = crop_box
    sx, sy = out_w / cw, out_h / ch
    result = []
    for (x, y, w, h) in regions:
        # Interseção com o crop
        ix0, iy0 = max(x, cx), max(y, cy)
        ix1, iy1 = min(x + w, cx + cw), min(y + h, cy + ch)
        if ix1 - ix0 <= 0 or iy1 - iy0 <= 0:
            continue
        if (ix1 - ix0) * (iy1 - iy0) < 0.2 * w * h:
            continue  # sobra desprezível dentro do crop
        result.append((
            int((ix0 - cx) * sx), int((iy0 - cy) * sy),
            int((ix1 - ix0) * sx), int((iy1 - iy0) * sy),
        ))
    return result


def _brand_cover(
    cover_path: str,
    watermark_path: Optional[str],
    qr_regions: Optional[list[tuple[int, int, int, int]]] = None,
    static_regions: Optional[list[tuple[int, int, int, int]]] = None,
) -> None:
    """
    Neutraliza marcas de terceiros na capa e aplica a logo do usuário:
    - regiões estáticas (logos de canal): borrão;
    - QR codes (das regiões detectadas no trecho + detecção na própria capa):
      borrão + logo do usuário centralizada;
    - pin da logo no canto superior direito (posição padrão de marca de canal).
    """
    import cv2
    import numpy as np
    from PIL import ImageFilter

    cover = Image.open(cover_path).convert("RGBA")

    # Detecção de QR na própria capa (backup das regiões vindas do trecho)
    try:
        arr = cv2.cvtColor(np.array(cover.convert("RGB")), cv2.COLOR_RGB2BGR)
        found, points = cv2.QRCodeDetector().detectMulti(arr)
    except Exception:
        found, points = False, None

    qr_boxes = [tuple(r) for r in (qr_regions or [])]
    if found and points is not None:
        for quad in points:
            xs, ys = quad[:, 0], quad[:, 1]
            x, y = int(xs.min()), int(ys.min())
            w, h = int(xs.max() - x), int(ys.max() - y)
            area_frac = (w * h) / (cover.width * cover.height)
            if 0.0005 <= area_frac <= 0.20:
                pad_x, pad_y = int(w * 0.12), int(h * 0.12)
                box = (max(0, x - pad_x), max(0, y - pad_y), w + 2 * pad_x, h + 2 * pad_y)
                if not any(_boxes_overlap(box, q) for q in qr_boxes):
                    qr_boxes.append(box)

    def _blur(x: int, y: int, w: int, h: int) -> None:
        x0, y0 = max(0, x), max(0, y)
        x1, y1 = min(cover.width, x + w), min(cover.height, y + h)
        if x1 - x0 > 2 and y1 - y0 > 2:
            patch = cover.crop((x0, y0, x1, y1)).filter(ImageFilter.GaussianBlur(24))
            cover.paste(patch, (x0, y0))

    for (x, y, w, h) in static_regions or []:
        _blur(x, y, w, h)
    for (x, y, w, h) in qr_boxes:
        _blur(x, y, w, h)

    if watermark_path and os.path.exists(watermark_path):
        logo = Image.open(watermark_path).convert("RGBA")

        # Logo sobre cada QR neutralizado
        for (x, y, w, h) in qr_boxes:
            scale = min(w * 0.9 / logo.width, h * 0.9 / logo.height)
            lw, lh = max(1, int(logo.width * scale)), max(1, int(logo.height * scale))
            resized = logo.resize((lw, lh), Image.LANCZOS)
            cover.alpha_composite(resized, (x + (w - lw) // 2, y + (h - lh) // 2))

        # Pin no canto superior direito (posição padrão de marca de canal)
        pin_w = int(cover.width * 0.18)
        pin_h = int(logo.height * pin_w / logo.width)
        pinned = logo.resize((pin_w, pin_h), Image.LANCZOS)
        cover.alpha_composite(pinned, (cover.width - pin_w - 28, 28))

    cover.convert("RGB").save(cover_path)


def _boxes_overlap(a: tuple, b: tuple) -> bool:
    ax, ay, aw, ah = a
    bx, by, bw, bh = b
    return not (ax + aw <= bx or bx + bw <= ax or ay + ah <= by or by + bh <= ay)


def _crop_to_cover(
    frame_path: str, cx: float, cy: float, width: int, height: int, output_path: str
) -> tuple[int, int, int, int]:
    """Recorta o frame na proporção da capa, centralizado no rosto (com clamp)."""
    img = Image.open(frame_path)
    src_w, src_h = img.size
    target_ratio = width / height

    if src_w / src_h > target_ratio:
        crop_h = src_h
        crop_w = int(src_h * target_ratio)
    else:
        crop_w = src_w
        crop_h = int(src_w / target_ratio)

    x = max(0, min(int(src_w * cx - crop_w / 2), src_w - crop_w))
    y = max(0, min(int(src_h * cy - crop_h / 2), src_h - crop_h))

    img.crop((x, y, x + crop_w, y + crop_h)).resize(
        (width, height), Image.LANCZOS
    ).save(output_path)
    return (x, y, crop_w, crop_h)
