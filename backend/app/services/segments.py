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

from app.utils.ffmpeg import get_duration, run_ffmpeg

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


def segments_without_pauses(
    start: float,
    end: float,
    pauses: Iterable[tuple[float, float]],
    margin: float,
) -> list[tuple[float, float]]:
    """
    O intervalo sem as pausas, deixando `margin` de cada lado de cada uma.

    A margem é o que evita a emenda seca, em que uma palavra emenda na outra sem
    fôlego. Pausa no início do clipe sai sem margem nesse lado: lá não há fala antes.
    """
    kept: list[tuple[float, float]] = []
    cursor = start
    for pause_start, pause_end in pauses:
        keep_until = pause_start + margin if pause_start > start else start
        resume_at = pause_end - margin if pause_end < end else end
        if resume_at <= keep_until:
            continue  # curta demais para sobrar algo depois das margens
        if keep_until > cursor:
            kept.append((cursor, keep_until))
        cursor = resume_at
    if end > cursor:
        kept.append((cursor, end))
    return kept


# Palavra que ficou sem tempo próprio ainda precisa de um instante na legenda.
_MIN_WORD_ON_SCREEN = 0.05


def _stitched_position(time: float, segments: list[tuple[float, float]]) -> float:
    """Onde um instante da fonte cai na linha do tempo costurada."""
    offset = 0.0
    for start, end in segments:
        if time < start:
            return offset  # caiu no que saiu: vai para a próxima emenda
        if time <= end:
            return offset + time - start
        offset += end - start
    return offset


def remap_words_keeping(
    words: list[dict],
    segments: list[tuple[float, float]],
    stitched_duration: Optional[float] = None,
) -> list[dict]:
    """
    Como `remap_words`, mas nenhuma palavra do intervalo some.

    No tempo morto do Siege a palavra que caiu fora do trecho saiu mesmo do vídeo.
    Numa pausa de podcast não: o que sai é medido como silêncio no áudio, então uma
    palavra com timestamp lá dentro foi dita em outro instante. `para noite.` aparece
    num silêncio de 1s, dita logo antes dele. Sumir com ela apagaria da legenda uma
    fala que continua no vídeo.

    `stitched_duration` é a duração REAL do arquivo costurado. Cada trecho arredonda
    para cima no limite do quadro, e a soma dos arredondamentos atrasaria a legenda
    a cada emenda: medido, 0,18s em 6 trechos. Sem ela, vale a soma nominal.
    """
    if not segments:
        return []
    first, last = segments[0][0], segments[-1][1]
    nominal = total_duration(segments)
    total = stitched_duration or nominal
    scale = total / nominal if nominal else 1.0

    remapped: list[dict] = []
    for word in words:
        if word["start"] < first or word["start"] >= last:
            continue
        moved = dict(word)
        moved["start"] = min(
            _stitched_position(word["start"], segments) * scale, total - _MIN_WORD_ON_SCREEN
        )
        moved["end"] = min(
            max(_stitched_position(word["end"], segments) * scale, moved["start"] + _MIN_WORD_ON_SCREEN),
            total,
        )
        remapped.append(moved)
    return remapped


async def compact_segments(
    job_id: str,
    clip_id: str,
    video_path: str,
    segments: list[tuple[float, float]],
    output_path: str,
) -> float:
    """
    Concatena os trechos num único arquivo. Devolve a duração REAL dele.

    Cada trecho entra como uma ENTRADA própria com `-ss`, e não como um filtro
    de corte sobre o vídeo inteiro: assim o ffmpeg busca direto no ponto em vez
    de decodificar os 40 minutos da fonte para descartar quase tudo.

    Real, e não a soma dos trechos, porque quem chama usa isto como fim do render:
    cada trecho arredonda para cima no limite do quadro, e a soma nominal cortava
    os últimos 0,18s de um clipe de 6 trechos, justo o respiro depois da frase.
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

    nominal = total_duration(segments)
    try:
        duration = await get_duration(output_path)
    except (RuntimeError, ValueError) as exc:
        logger.warning(f"[{job_id}] Clip {clip_id}: sem a duração real ({exc}) — vale a nominal")
        duration = nominal
    logger.info(
        f"[{job_id}] Clip {clip_id}: {len(segments)} trecho(s) costurado(s) "
        f"→ {duration:.1f}s (tempo morto removido: "
        f"{segments[-1][1] - segments[0][0] - nominal:.1f}s)"
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
