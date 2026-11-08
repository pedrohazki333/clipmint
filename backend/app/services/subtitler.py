"""
Gerador de legendas .ASS nos 3 modos suportados pelo ClipMint.

Modos:
  - word_highlight: Uma palavra por vez destacada em amarelo (estilo karaokê moderno).
    Ideal para TikTok/Reels — mantém atenção máxima.
  - traditional: Blocos de 2-3 palavras com timing tradicional.
    Mais discreto, adequado para conteúdo mais sério.
  - none: Sem legenda — apenas o crop 9:16.
"""

import logging
from dataclasses import dataclass
from typing import List, Optional

from app.services.fonts import ass_font_size, font_path, load_font

logger = logging.getLogger(__name__)

# ─── Constantes de estilo ASS ─────────────────────────────────────────────────

# Fonte principal das legendas
FONT_NAME = "Arial"
FONT_SIZE_WORD = 84       # word_highlight mode — grande, estilo TikTok
FONT_SIZE_TRADITIONAL = 48

# Cores no formato ASS (&HAABBGGRR — alpha, blue, green, red)
COLOR_WHITE = "&H00FFFFFF"
COLOR_YELLOW = "&H0000FFFF"
COLOR_BLACK_OUTLINE = "&H00000000"
COLOR_SHADOW = "&H80000000"

# Margem vertical em pixels a partir da borda inferior (PlayResY=1920).
# No layout capa+vídeo (vídeo ocupa 768–1920px), MarginV 440 posiciona a
# legenda a ~62% da área do vídeo — abaixo do rosto, acima da UI do TikTok
MARGIN_V_WORD = 440
MARGIN_V_TRADITIONAL = 200

# Quanto tempo (s) a última palavra da linha permanece na tela após ser falada
LINE_HOLD = 0.30


def _ass_time(seconds: float) -> str:
    """Converte segundos para formato ASS: H:MM:SS.cc"""
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = seconds % 60
    cs = int((s - int(s)) * 100)
    return f"{h}:{m:02d}:{int(s):02d}.{cs:02d}"


def _ass_header(
    width: int = 1080,
    height: int = 1920,
    margin_v: Optional[int] = None,
) -> str:
    """
    Gera o cabeçalho do arquivo .ASS.

    Tamanhos de fonte, contorno e margens são definidos para o canvas de
    referência (1080x1920) e escalados junto com a largura — assim a legenda
    ocupa a mesma proporção da tela em qualquer resolução de saída.

    Args:
        margin_v: distância do texto até a borda INFERIOR do canvas, já em
            pixels do canvas final. None usa a margem padrão de cada modo.
    """
    k = width / 1080
    px = lambda v: max(1, int(round(v * k)))  # noqa: E731

    mv_word = px(MARGIN_V_WORD) if margin_v is None else margin_v
    mv_trad = px(MARGIN_V_TRADITIONAL) if margin_v is None else margin_v

    return f"""[Script Info]
ScriptType: v4.00+
PlayResX: {width}
PlayResY: {height}
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: WordHighlight,{FONT_NAME},{px(FONT_SIZE_WORD)},{COLOR_WHITE},&H000000FF,{COLOR_BLACK_OUTLINE},{COLOR_SHADOW},-1,0,0,0,100,100,0,0,1,{px(5)},{px(2)},2,{px(40)},{px(40)},{mv_word},1
Style: Traditional,{FONT_NAME},{px(FONT_SIZE_TRADITIONAL)},{COLOR_WHITE},&H000000FF,{COLOR_BLACK_OUTLINE},{COLOR_SHADOW},-1,0,0,0,100,100,0,0,1,{px(4)},{px(1)},2,{px(40)},{px(40)},{mv_trad},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""


def _generate_word_highlight_events(
    words: List[dict],
    start_offset: float,
) -> List[str]:
    """
    Gera eventos ASS no modo word_highlight (karaokê).

    Para cada palavra, mostra a linha completa com a palavra atual em amarelo
    e levemente ampliada. Os eventos são contínuos: cada um dura do início da
    palavra ativa até o início da próxima — a linha nunca pisca entre palavras,
    mesmo com pausas na fala. A última palavra segura a linha por LINE_HOLD
    (limitado ao início da linha seguinte).
    """
    events = []
    LINE_SIZE = 3  # poucas palavras por linha — fonte grande sem quebrar

    # Agrupa palavras em linhas
    lines: List[List[dict]] = []
    for i in range(0, len(words), LINE_SIZE):
        lines.append(words[i:i + LINE_SIZE])

    for line_idx, line_words in enumerate(lines):
        next_line_start = (
            lines[line_idx + 1][0]["start"] - start_offset
            if line_idx + 1 < len(lines)
            else None
        )

        for active_idx, active_word in enumerate(line_words):
            event_start = max(0.0, active_word["start"] - start_offset)

            # Timing contínuo: o evento vai até a próxima palavra assumir
            if active_idx + 1 < len(line_words):
                event_end = line_words[active_idx + 1]["start"] - start_offset
            else:
                event_end = active_word["end"] - start_offset + LINE_HOLD
                if next_line_start is not None:
                    event_end = min(event_end, next_line_start)

            if event_end <= event_start:
                continue

            # Palavra ativa em amarelo, ampliada; {\r} restaura o estilo base
            parts = []
            for i, w in enumerate(line_words):
                if i == active_idx:
                    parts.append(r"{\c&H0000FFFF&\fscx112\fscy112}" + w["text"] + r"{\r}")
                else:
                    parts.append(w["text"])
            line_text = " ".join(parts)

            events.append(
                f"Dialogue: 0,{_ass_time(event_start)},{_ass_time(event_end)},"
                f"WordHighlight,,0,0,0,,{line_text}"
            )

    return events


def _generate_traditional_events(
    words: List[dict],
    start_offset: float,
) -> List[str]:
    """
    Gera eventos ASS no modo traditional (blocos de 3 palavras).

    Cada bloco fica na tela do início da primeira até o fim da última palavra.
    """
    events = []
    BLOCK_SIZE = 3

    for i in range(0, len(words), BLOCK_SIZE):
        block = words[i:i + BLOCK_SIZE]
        block_start = block[0]["start"] - start_offset
        block_end = block[-1]["end"] - start_offset

        if block_start < 0:
            continue

        text = " ".join(w["text"] for w in block)
        events.append(
            f"Dialogue: 0,{_ass_time(block_start)},{_ass_time(block_end)},"
            f"Traditional,,0,0,0,,{text}"
        )

    return events


# ─── Legenda do estilo do clipe ───────────────────────────────────────────────

#: Fatores de P/M/G. M são as medidas da especificação (docs/LAYOUTS_V2.md).
_SIZE_FACTORS = {"P": 0.85, "M": 1.0, "G": 1.15}

# Até onde a linha pode ir. Centrada em x=540 e sem entrar na coluna da direita
# (x=930), sobram 780px; descontando a caixa da palavra e o contorno, 742. Medido: 20%
# das linhas de 3 palavras a 88px passam disso, e por isso a linha é montada por largura.
CAPTION_MAX_WIDTH = 742
CAPTION_MAX_WORDS = 3


@dataclass(frozen=True)
class CaptionGeometry:
    """Onde a legenda fica neste layout, já em pixels do canvas."""

    canvas_w: int
    canvas_h: int
    center_y: int
    size: int
    outline: int
    max_width: int


def caption_geometry(
    layout: str,
    tamanho: str = "M",
    canvas_w: int = 1080,
    canvas_h: int = 1920,
    margin_v: Optional[int] = None,
) -> CaptionGeometry:
    """
    A posição da legenda em cada layout.

    `original` mantém a resolução da fonte, que pode ser deitada: a escala sai da menor
    proporção e a legenda desce para perto da borda, onde costuma ficar num vídeo 16:9.
    """
    fator = _SIZE_FACTORS.get(tamanho, 1.0)
    if layout == "original":
        k = min(canvas_w / 1080, canvas_h / 1920)
        size = max(16, round(88 * k * fator))
        return CaptionGeometry(
            canvas_w, canvas_h, round(canvas_h * 0.84), size,
            max(2, round(9 * k)), round(canvas_w * 0.9),
        )

    k = canvas_w / 1080
    base, contorno = (80, 8) if layout == "cover" else (88, 9)
    size = round(base * k * fator)
    if margin_v is not None:
        center_y = canvas_h - margin_v - size // 2
    else:
        center_y = round(1205 * canvas_h / 1920)
    return CaptionGeometry(
        canvas_w, canvas_h, center_y, size, round(contorno * k), round(CAPTION_MAX_WIDTH * k)
    )


def _ass_color(hex_color: str) -> str:
    """#RRGGBB → &HBBGGRR&, a ordem invertida que o ASS usa."""
    return f"&H{hex_color[5:7]}{hex_color[3:5]}{hex_color[1:3]}&".upper()


def _ass_text(text: str) -> str:
    """Tira o que o ASS leria como comando em vez de texto."""
    return text.replace("\\", "").replace("{", "").replace("}", "")


def _line_width(line: List[dict], font, gap: Optional[float] = None) -> float:
    """A largura da linha. `gap` troca o espaço normal entre as palavras."""
    if gap is None:
        return font.getlength(" ".join(w["text"] for w in line))
    return sum(font.getlength(w["text"]) for w in line) + gap * (len(line) - 1)


def group_caption_lines(
    words: List[dict],
    font,
    max_width: float,
    max_words: int = CAPTION_MAX_WORDS,
    gap: Optional[float] = None,
) -> List[List[dict]]:
    """
    Agrupa as palavras em linhas que cabem na largura.

    Fim de frase fecha a linha, mesmo que ainda caiba mais: emendar o começo da frase
    seguinte na mesma linha atrapalha mais a leitura do que uma linha curta.
    """
    lines: List[List[dict]] = []
    current: List[dict] = []
    for word in words:
        if current and (
            len(current) >= max_words
            or _line_width(current + [word], font, gap) > max_width
        ):
            lines.append(current)
            current = []
        current.append(word)
        if word["text"].rstrip().endswith((".", "!", "?", "…")):
            lines.append(current)
            current = []
    if current:
        lines.append(current)
    return lines


def _line_scale(line: List[dict], font, max_width: float) -> str:
    """Reduz só a linha que nem sozinha coube: uma palavra enorme não pode vazar."""
    width = font.getlength(" ".join(w["text"] for w in line))
    if width <= max_width:
        return ""
    percent = int(100 * max_width / width)
    return rf"\fscx{percent}\fscy{percent}"


def _styled_header(family: str, geo: CaptionGeometry, ass_size: int) -> str:
    return f"""[Script Info]
ScriptType: v4.00+
PlayResX: {geo.canvas_w}
PlayResY: {geo.canvas_h}
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Caption,{family},{ass_size},{COLOR_WHITE},&H000000FF,{COLOR_BLACK_OUTLINE},&H00000000,0,0,0,0,100,100,0,0,1,{geo.outline},0,5,0,0,0,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""


def _word_states(lines: List[List[dict]], start_offset: float):
    """
    Cada estado da legenda: (linha, índice da palavra falada, início, fim).

    Contínuo: cada estado dura até a palavra seguinte assumir, e a linha não pisca entre
    palavras, mesmo com pausa na fala. A última palavra segura a linha por LINE_HOLD,
    limitado ao início da linha seguinte.
    """
    for line_index, line in enumerate(lines):
        next_start = (
            lines[line_index + 1][0]["start"] - start_offset
            if line_index + 1 < len(lines)
            else None
        )
        for active, word in enumerate(line):
            start = max(0.0, word["start"] - start_offset)
            if active + 1 < len(line):
                end = line[active + 1]["start"] - start_offset
            else:
                end = word["end"] - start_offset + LINE_HOLD
                if next_start is not None:
                    end = min(end, next_start)
            if end > start:
                yield line, active, start, end


def _color_events(
    lines: List[List[dict]],
    start_offset: float,
    geo: CaptionGeometry,
    color: str,
    font,
) -> List[str]:
    """Estilo "cor": a linha inteira na tela, e a palavra falada na cor escolhida."""
    events: List[str] = []
    active_color = _ass_color(color)
    white = _ass_color("#FFFFFF")
    position = rf"\an5\pos({geo.canvas_w // 2},{geo.center_y})"

    for line, active, start, end in _word_states(lines, start_offset):
        scale = _line_scale(line, font, geo.max_width)
        parts = []
        for index, w in enumerate(line):
            text = _ass_text(w["text"])
            parts.append(
                rf"{{\1c{active_color}}}{text}{{\1c{white}}}" if index == active else text
            )
        events.append(
            f"Dialogue: 0,{_ass_time(start)},{_ass_time(end)},Caption,,0,0,0,,"
            f"{{{position}{scale}}}{' '.join(parts)}"
        )
    return events


#: A caixa da palavra falada, na escala de 1080 de largura.
BOX_PADDING_X = 19
BOX_RADIUS = 19
#: Texto dentro da caixa, a mesma cor em que o contraste do estilo é medido.
BOX_TEXT_COLOR = "#0B0B0C"
# Quanto sobra entre a caixa e a palavra vizinha. No teste com o espaço normal da fonte
# as duas quase encostavam, e a palavra ao lado parecia parte da caixa.
BOX_NEIGHBOR_GAP = 12
# Constante que aproxima um quarto de círculo com uma curva de Bézier.
_BEZIER_CIRCLE = 0.5523


def box_word_gap(geo: CaptionGeometry) -> float:
    return (BOX_PADDING_X + BOX_NEIGHBOR_GAP) * geo.canvas_w / 1080


def rounded_box_drawing(left: float, top: float, right: float, bottom: float, radius: float) -> str:
    """Um retângulo de cantos redondos nos comandos de desenho do ASS (\\p)."""
    l, t, r, b = round(left), round(top), round(right), round(bottom)
    rad = min(radius, (r - l) / 2, (b - t) / 2)
    k = _BEZIER_CIRCLE * rad

    def n(value: float) -> int:
        return round(value)

    return (
        f"m {n(l + rad)} {t} l {n(r - rad)} {t} "
        f"b {n(r - rad + k)} {t} {r} {n(t + rad - k)} {r} {n(t + rad)} "
        f"l {r} {n(b - rad)} "
        f"b {r} {n(b - rad + k)} {n(r - rad + k)} {b} {n(r - rad)} {b} "
        f"l {n(l + rad)} {b} "
        f"b {n(l + rad - k)} {b} {l} {n(b - rad + k)} {l} {n(b - rad)} "
        f"l {l} {n(t + rad)} "
        f"b {l} {n(t + rad - k)} {n(l + rad - k)} {t} {n(l + rad)} {t}"
    )


def _box_events(
    lines: List[List[dict]],
    start_offset: float,
    geo: CaptionGeometry,
    color: str,
    font,
) -> List[str]:
    """
    Estilo "caixa": a palavra falada ganha uma caixa na cor escolhida.

    O ASS não faz caixa por palavra, e por isso ela é um desenho vetorial (\\p), medido
    com as mesmas métricas da fonte que o libass usa. Cada palavra entra com posição
    própria: deixar o libass distribuir a linha separaria texto e caixa em meio pixel de
    diferença de medida. Comparado a sobrepor um PNG por estado, em que um clipe tem
    centenas de estados e cada um é mais uma entrada no filtro, isto é só texto no .ass.
    """
    k = geo.canvas_w / 1080
    gap = box_word_gap(geo)
    padding, radius = BOX_PADDING_X * k, BOX_RADIUS * k
    ascent, descent = font.getmetrics()
    box_color, ink = _ass_color(color), _ass_color(BOX_TEXT_COLOR)
    y = geo.center_y

    events: List[str] = []
    for line, active, start, end in _word_states(lines, start_offset):
        widths = [font.getlength(w["text"]) for w in line]
        total = _line_width(line, font, gap)
        factor = min(1.0, geo.max_width / total) if total else 1.0
        scale = "" if factor == 1.0 else rf"\fscx{int(factor * 100)}\fscy{int(factor * 100)}"
        height = (ascent + descent) * factor
        timing = f"{_ass_time(start)},{_ass_time(end)}"

        x = geo.canvas_w / 2 - total * factor / 2
        for index, (word, width) in enumerate(zip(line, widths)):
            width *= factor
            center = x + width / 2
            text = _ass_text(word["text"])
            if index == active:
                box = rounded_box_drawing(
                    x - padding, y - height / 2, x + width + padding, y + height / 2, radius
                )
                events.append(
                    f"Dialogue: 0,{timing},Caption,,0,0,0,,"
                    rf"{{\an7\pos(0,0)\bord0\shad0\1c{box_color}\p1}}{box}{{\p0}}"
                )
                events.append(
                    f"Dialogue: 1,{timing},Caption,,0,0,0,,"
                    rf"{{\an5\pos({center:.1f},{y})\bord0\shad0\1c{ink}{scale}}}{text}"
                )
            else:
                events.append(
                    f"Dialogue: 1,{timing},Caption,,0,0,0,,"
                    rf"{{\an5\pos({center:.1f},{y}){scale}}}{text}"
                )
            x += width + gap * factor
    return events


def _block_events(
    lines: List[List[dict]], start_offset: float, geo: CaptionGeometry, font
) -> List[str]:
    """Modo `traditional`: o bloco de palavras, sem destaque nenhum."""
    position = rf"\an5\pos({geo.canvas_w // 2},{geo.center_y})"
    events: List[str] = []
    for line in lines:
        start = line[0]["start"] - start_offset
        end = line[-1]["end"] - start_offset
        if start < 0 or end <= start:
            continue
        text = " ".join(_ass_text(w["text"]) for w in line)
        scale = _line_scale(line, font, geo.max_width)
        events.append(
            f"Dialogue: 0,{_ass_time(start)},{_ass_time(end)},Caption,,0,0,0,,"
            f"{{{position}{scale}}}{text}"
        )
    return events


def generate_styled_captions(
    words: List[dict],
    start_time: float,
    end_time: float,
    subtitle_mode: str,
    output_path: str,
    style,
    geometry: CaptionGeometry,
    family: str,
) -> None:
    """
    A legenda com o estilo do perfil, em qualquer layout.

    Os três modos continuam: `word_highlight` destaca a palavra falada, `traditional`
    mostra blocos sem destaque e `none` não gera nada.
    """
    if subtitle_mode == "none":
        return

    segment_words = [
        {**w, "end": min(w["end"], end_time)}
        for w in words
        if start_time <= w["start"] < end_time
    ]
    if not segment_words:
        logger.warning(f"No words found between {start_time:.1f}s and {end_time:.1f}s")
        return

    font = load_font(style.fonte, "legenda", geometry.size)
    caixa = subtitle_mode == "word_highlight" and style.legenda.estilo == "caixa"
    lines = group_caption_lines(
        segment_words, font, geometry.max_width, gap=box_word_gap(geometry) if caixa else None
    )
    if caixa:
        events = _box_events(lines, start_time, geometry, style.legenda.cor, font)
    elif subtitle_mode == "word_highlight":
        events = _color_events(lines, start_time, geometry, style.legenda.cor, font)
    else:
        events = _block_events(lines, start_time, geometry, font)

    with open(output_path, "w", encoding="utf-8") as f:
        ass_size = ass_font_size(font_path(style.fonte, "legenda"), geometry.size)
        f.write(_styled_header(family, geometry, ass_size) + "\n".join(events) + "\n")
    logger.info(f"Subtitles written to: {output_path} ({len(events)} events)")


def generate_ass_subtitles(
    words: List[dict],
    start_time: float,
    end_time: float,
    subtitle_mode: str,
    output_path: str,
    canvas_w: int = 1080,
    canvas_h: int = 1920,
    margin_v: Optional[int] = None,
) -> None:
    """
    Gera arquivo .ASS de legendas para um segmento de vídeo, sem estilo de perfil.

    Args:
        words: Lista de palavras com timestamps globais do vídeo original.
        start_time: Início do clip (segundos).
        end_time: Fim do clip (segundos).
        subtitle_mode: 'word_highlight', 'traditional', ou 'none'.
        output_path: Caminho de saída do arquivo .ASS.
        canvas_w/canvas_h: resolução do clipe final (o estilo escala junto).
        margin_v: distância até a borda inferior, em pixels do canvas final.
            None = margem padrão do modo (layout capa+vídeo).
    """
    if subtitle_mode == "none":
        return

    # Filtra palavras do segmento. Vale onde a palavra COMEÇA: o fim do clipe pode
    # cair num silêncio escondido no timestamp dela, como no `mano?` que dura 1,6s
    # com 0,8s calado. Exigir o fim lá dentro apagava da legenda uma palavra dita
    # por inteiro.
    segment_words = [
        {**w, "end": min(w["end"], end_time)}
        for w in words
        if start_time <= w["start"] < end_time
    ]

    if not segment_words:
        logger.warning(f"No words found between {start_time:.1f}s and {end_time:.1f}s")
        return

    header = _ass_header(canvas_w, canvas_h, margin_v)

    if subtitle_mode == "word_highlight":
        events = _generate_word_highlight_events(segment_words, start_offset=start_time)
    else:  # traditional
        events = _generate_traditional_events(segment_words, start_offset=start_time)

    content = header + "\n".join(events) + "\n"

    with open(output_path, "w", encoding="utf-8") as f:
        f.write(content)

    logger.info(f"Subtitles written to: {output_path} ({len(events)} events)")
