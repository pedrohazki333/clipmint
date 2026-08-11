"""
Clipes costurados a partir de trechos separados do vídeo.

Um ace de Siege raramente acontece em quinze segundos: os abates se espalham
pelo round, com caminhada e silêncio no meio. Entregar a janela inteira mata a
retenção; entregar só um pedaço joga fora metade da jogada. A saída é montar um
clipe com os trechos que importam, emendados.

O render final não sabe (nem precisa saber) disso. Aqui os trechos são
concatenados num arquivo temporário e os timestamps das palavras são
remapeados para essa nova linha do tempo; o clipper então trabalha nesse
arquivo como se fosse um vídeo comum, com um único corte contínuo. É o que
mantém a facecam, a faixa, o banner e as legendas funcionando sem tocar no
filtergraph.
"""

import logging
import os
from typing import Iterable, Optional

from app.utils.ffmpeg import run_ffmpeg

logger = logging.getLogger(__name__)

# Qualidade do intermediário: o clipe passa por DUAS codificações (esta e a do
# render). CRF baixo aqui é o que impede a segunda de partir de uma imagem já
# degradada — o arquivo é temporário, então o tamanho não importa.
_INTERMEDIATE_CRF = "16"
_INTERMEDIATE_PRESET = "veryfast"


def total_duration(segments: Iterable[tuple[float, float]]) -> float:
    """Duração somada dos trechos — a duração do clipe final."""
    return sum(max(0.0, end - start) for start, end in segments)


def remap_words(words: list[dict], segments: list[tuple[float, float]]) -> list[dict]:
    """
    Reposiciona as palavras na linha do tempo do clipe costurado.

    Palavra que cai no tempo morto descartado some junto — é exatamente o que
    se quer, senão a legenda mostraria fala que não está mais no vídeo.
    """
    remapped: list[dict] = []
    offset = 0.0
    for start, end in segments:
        for word in words:
            if word["start"] >= start and word["end"] <= end:
                moved = dict(word)
                moved["start"] = word["start"] - start + offset
                moved["end"] = word["end"] - start + offset
                remapped.append(moved)
        offset += end - start
    return remapped


async def compact_segments(
    job_id: str,
    clip_id: str,
    video_path: str,
    segments: list[tuple[float, float]],
    output_path: str,
) -> float:
    """
    Concatena os trechos num único arquivo. Devolve a duração resultante.

    Cada trecho entra como uma ENTRADA própria com `-ss`, e não como um filtro
    de corte sobre o vídeo inteiro: assim o ffmpeg busca direto no ponto em vez
    de decodificar os 40 minutos da fonte para descartar quase tudo.
    """
    inputs: list[str] = []
    for start, end in segments:
        inputs += ["-ss", f"{start:.3f}", "-t", f"{end - start:.3f}", "-i", video_path]

    streams = "".join(f"[{i}:v][{i}:a]" for i in range(len(segments)))
    filtergraph = f"{streams}concat=n={len(segments)}:v=1:a=1[v][a]"

    await run_ffmpeg(
        *inputs,
        "-filter_complex", filtergraph,
        "-map", "[v]", "-map", "[a]",
        "-c:v", "libx264", "-crf", _INTERMEDIATE_CRF, "-preset", _INTERMEDIATE_PRESET,
        "-c:a", "aac", "-b:a", "192k",
        output_path,
        description=f"Costura {len(segments)} trecho(s) do clip {clip_id}",
    )

    duration = total_duration(segments)
    logger.info(
        f"[{job_id}] Clip {clip_id}: {len(segments)} trecho(s) costurado(s) "
        f"→ {duration:.1f}s (tempo morto removido: "
        f"{segments[-1][1] - segments[0][0] - duration:.1f}s)"
    )
    return duration


def cleanup(path: Optional[str]) -> None:
    """Remove o intermediário — ele não serve para nada depois do render."""
    if not path:
        return
    try:
        os.remove(path)
    except OSError as exc:  # não vale derrubar o pipeline por arquivo temporário
        logger.warning(f"Falha ao remover intermediário {path}: {exc}")
