"""
Trechos indicados à mão, do jeito que alguém anota assistindo.

Quem marca um momento não digita segundos: anota "3:24 - 4:10", que é o que
aparece na barra do player. Este módulo aceita essa anotação como ela é —
mm:ss, h:mm:ss ou segundos puros, separados por vírgula, ponto-e-vírgula ou
quebra de linha — e devolve intervalos em segundos.

A ORDEM DIGITADA É PRESERVADA e isso é deliberado: num compilado ela é a
montagem. Quem escreve "12:05-12:40, 3:24-4:10" está pedindo para abrir pelo
trecho dos 12 minutos, do mesmo jeito que o compilado de referência abre por um
momento que acontece na hora 1:04 do vídeo.

Erro aqui é do usuário, não do sistema: as mensagens dizem qual pedaço está
errado, porque "entrada inválida" não ajuda ninguém a consertar a própria lista.
"""

import re
from typing import Iterable

# Separadores entre trechos e entre início e fim. O travessão aparece quando o
# texto veio de um editor que "embeleza" hífen, e o "às"/"a" aparece porque é
# como se escreve à mão.
_ENTRY_SPLIT = re.compile(r"[,;\n]+")
# O "a" solto entra porque "12:05 a 12:40" é como se escreve em português.
# A alternância é segura: em "até", o caractere seguinte ao "a" é palavra,
# então \ba\b não casa e o "até" continua sendo lido inteiro.
_RANGE_SPLIT = re.compile(r"\s*(?:-->|->|–|—|\.\.+|\baté\b|\bate\b|\bàs\b|\bas\b|\bto\b|\ba\b|-)\s*")
# Duas formas: segundos corridos ("204", "3723") ou com dois pontos
# ("3:24", "1:02:03"). Sem os dois casos separados, um número de três
# dígitos em segundos era recusado como tempo inválido.
_TIMECODE = re.compile(r"^(?:\d{1,6}|\d{1,3}(?::\d{1,2}){1,2})(?:[.,]\d+)?$")


class TimecodeError(ValueError):
    """A lista de trechos não pôde ser lida. A mensagem diz qual pedaço."""


def parse_timecode(raw: str) -> float:
    """
    "3:24" → 204.0, "1:02:03" → 3723.0, "204" → 204.0, "3:24.5" → 204.5.

    Minutos e segundos acima de 59 são aceitos ("90:00" = 1h30): quem anota
    corrido não converte para horas, e recusar isso seria pedantismo.
    """
    text = raw.strip().replace(",", ".")
    if not text or not _TIMECODE.match(text):
        raise TimecodeError(f'"{raw.strip()}" não é um tempo válido — use 3:24, 1:02:03 ou 204')

    parts = text.split(":")
    seconds = 0.0
    for part in parts:
        seconds = seconds * 60 + float(part)
    return seconds


def parse_ranges(
    text: str, min_duration: float = 1.0, max_ranges: int = 20
) -> list[tuple[float, float]]:
    """
    Os trechos anotados, em segundos, na ordem em que foram escritos.

    Levanta TimecodeError com a mensagem apontando o pedaço problemático.
    Texto vazio devolve lista vazia — "não indiquei nada" é um caso normal, não
    um erro.
    """
    if not text or not text.strip():
        return []

    ranges: list[tuple[float, float]] = []
    for entry in _ENTRY_SPLIT.split(text):
        entry = entry.strip()
        if not entry:
            continue

        sides = [side for side in _RANGE_SPLIT.split(entry) if side.strip()]
        if len(sides) != 2:
            raise TimecodeError(
                f'"{entry}" precisa de início e fim — escreva algo como 3:24 - 4:10'
            )

        start, end = parse_timecode(sides[0]), parse_timecode(sides[1])
        if end <= start:
            raise TimecodeError(f'"{entry}": o fim tem que vir depois do início')
        if end - start < min_duration:
            raise TimecodeError(
                f'"{entry}" tem {end - start:.0f}s — o mínimo é {min_duration:.0f}s'
            )
        ranges.append((start, end))

    if len(ranges) > max_ranges:
        raise TimecodeError(f"{len(ranges)} trechos indicados; o máximo é {max_ranges}")

    _reject_overlaps(ranges)
    return ranges


def _reject_overlaps(ranges: Iterable[tuple[float, float]]) -> None:
    """
    Dois trechos que se cruzam quase sempre são erro de digitação.

    Não são fundidos em silêncio: quem indicou à mão sabe o que quer, e juntar
    sem avisar entregaria um clipe diferente do pedido.
    """
    ordered = sorted(ranges)
    for (a_start, a_end), (b_start, b_end) in zip(ordered, ordered[1:]):
        if b_start < a_end:
            raise TimecodeError(
                f"os trechos {_fmt(a_start)}-{_fmt(a_end)} e "
                f"{_fmt(b_start)}-{_fmt(b_end)} se sobrepõem"
            )


def _fmt(seconds: float) -> str:
    """Segundos de volta para mm:ss, para a mensagem falar a língua do usuário."""
    total = int(seconds)
    hours, remainder = divmod(total, 3600)
    minutes, secs = divmod(remainder, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{minutes}:{secs:02d}"
