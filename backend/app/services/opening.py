"""
O gancho de abertura: a fala mais forte do clipe tocada antes do começo dele.

O clipe abre com até 4 segundos do momento que prende ("pronto, morremo") e só
então começa do início. A fala sai de dentro do próprio clipe e aparece de novo
no lugar dela: o começo funciona como promessa do que vem.

Quem escolhe a fala é a análise, como TEXTO (campo `abertura`), e não como
tempo: o modelo copia frases da transcrição muito melhor do que acerta
timestamps. O tempo vem daqui, das palavras da transcrição — a fala começa na
primeira palavra e termina na última, inteira. Frase que não se acha, ou que
passa de 4 s, fica de fora: um gancho cortado no meio é pior que nenhum.
"""

from __future__ import annotations

import logging
import re
import unicodedata
from typing import Optional

logger = logging.getLogger(__name__)

#: "Pronto, morremo" dura menos de um segundo e é exatamente o tipo de gancho
#: que se quer: o piso só barra a palavra solta.
MIN_SECONDS = 0.6
MAX_SECONDS = 4.0
#: Começar um pouco antes da primeira palavra: o ataque da consoante vem antes
#: do timestamp, e sem isto o "p" de "pronto" some.
_LEAD_IN = 0.08
#: Depois da última palavra, a respiração que fecha a frase — sem invadir a
#: próxima fala.
_TAIL = 0.25
#: Fração das palavras da citação que precisam bater, na ordem.
_MATCH = 0.8
#: Uma abertura que já está no começo do clipe não abre nada: é só repetir.
_MIN_OFFSET = 3.0


def _norm(texto: str) -> str:
    sem_acento = unicodedata.normalize("NFKD", texto.lower())
    sem_acento = "".join(c for c in sem_acento if not unicodedata.combining(c))
    return re.sub(r"[^a-z0-9]+", "", sem_acento)


def _tokens(texto: str) -> list[str]:
    return [t for t in (_norm(p) for p in texto.split()) if t]


def find_opening(
    words: list[dict],
    start: float,
    end: float,
    quote: Optional[str],
) -> Optional[tuple[float, float, str]]:
    """
    Onde a citação foi dita dentro de [start, end], como (início, fim, texto).

    None quando não há citação, ela não é achada, ou não cabe em 1–4 s.
    """
    alvo = _tokens(quote or "")
    if not alvo:
        return None

    dentro = [w for w in words if w["start"] >= start and w["end"] <= end]
    normal = [_norm(w["text"]) for w in dentro]
    n = len(alvo)

    melhor: tuple[float, int] | None = None
    for i in range(0, max(0, len(dentro) - n) + 1):
        janela = normal[i:i + n]
        acertos = sum(1 for a, b in zip(alvo, janela) if a == b)
        nota = acertos / n
        if nota >= _MATCH and (melhor is None or nota > melhor[0]):
            melhor = (nota, i)
            if nota == 1.0:
                break
    if melhor is None:
        logger.info(f"Abertura não encontrada no clipe [{start:.1f}-{end:.1f}]: {quote!r}")
        return None

    i = melhor[1]
    primeira, ultima = dentro[i], dentro[i + n - 1]
    ini = max(start, primeira["start"] - _LEAD_IN)
    proxima = dentro[i + n]["start"] if i + n < len(dentro) else end
    fim = min(end, ultima["end"] + _TAIL, max(ultima["end"], proxima - 0.02))

    duracao = fim - ini
    if not (MIN_SECONDS <= duracao <= MAX_SECONDS):
        logger.info(f"Abertura fora de {MIN_SECONDS:.1f}–{MAX_SECONDS:.0f}s ({duracao:.1f}s): {quote!r}")
        return None
    if ini - start < _MIN_OFFSET:
        logger.info(f"Abertura já no começo do clipe ({ini - start:.1f}s): {quote!r}")
        return None

    texto = " ".join(w["text"] for w in dentro[i:i + n])
    return round(ini, 3), round(fim, 3), texto


def shift_words(words: list[dict], offset: float) -> list[dict]:
    """As palavras empurradas `offset` segundos para a frente na linha do tempo."""
    return [{**w, "start": w["start"] + offset, "end": w["end"] + offset} for w in words]
