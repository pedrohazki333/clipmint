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
from typing import List

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


def _ass_header(width: int = 1080, height: int = 1920) -> str:
    """Gera o cabeçalho do arquivo .ASS."""
    return f"""[Script Info]
ScriptType: v4.00+
PlayResX: {width}
PlayResY: {height}
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: WordHighlight,{FONT_NAME},{FONT_SIZE_WORD},{COLOR_WHITE},&H000000FF,{COLOR_BLACK_OUTLINE},{COLOR_SHADOW},-1,0,0,0,100,100,0,0,1,5,2,2,40,40,{MARGIN_V_WORD},1
Style: Traditional,{FONT_NAME},{FONT_SIZE_TRADITIONAL},{COLOR_WHITE},&H000000FF,{COLOR_BLACK_OUTLINE},{COLOR_SHADOW},-1,0,0,0,100,100,0,0,1,4,1,2,40,40,{MARGIN_V_TRADITIONAL},1

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


def generate_ass_subtitles(
    words: List[dict],
    start_time: float,
    end_time: float,
    subtitle_mode: str,
    output_path: str,
) -> None:
    """
    Gera arquivo .ASS de legendas para um segmento de vídeo.

    Args:
        words: Lista de palavras com timestamps globais do vídeo original.
        start_time: Início do clip (segundos).
        end_time: Fim do clip (segundos).
        subtitle_mode: 'word_highlight', 'traditional', ou 'none'.
        output_path: Caminho de saída do arquivo .ASS.
    """
    if subtitle_mode == "none":
        return

    # Filtra palavras do segmento
    segment_words = [
        w for w in words
        if w["start"] >= start_time and w["end"] <= end_time
    ]

    if not segment_words:
        logger.warning(f"No words found between {start_time:.1f}s and {end_time:.1f}s")
        return

    header = _ass_header()

    if subtitle_mode == "word_highlight":
        events = _generate_word_highlight_events(segment_words, start_offset=start_time)
    else:  # traditional
        events = _generate_traditional_events(segment_words, start_offset=start_time)

    content = header + "\n".join(events) + "\n"

    with open(output_path, "w", encoding="utf-8") as f:
        f.write(content)

    logger.info(f"Subtitles written to: {output_path} ({len(events)} events)")
