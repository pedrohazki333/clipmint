"""
A palavra do título que sai na cor da marca.

Quem escolhe é a análise, que entendeu o clipe: o campo `hook_keyword`. Só que é uma
resposta de modelo, e o título é o que vai para a tela: a palavra precisa estar nele,
senão não há o que pintar. Sem resposta válida, ou num job anterior a este campo, a
escolha cai numa heurística simples, porque título todo branco custa mais que um
destaque razoável.
"""

import re
import unicodedata
from typing import Optional

_WORD = re.compile(r"[\w$%]+", re.UNICODE)

# Palavras que nunca são o impacto de uma frase.
_STOPWORDS = frozenset(
    """
    a as ao aos o os e é em no na nos nas num numa de do da dos das por para pra pro
    com sem um uma uns umas que se sua seu suas seus minha meu minhas meus ele ela eles
    elas eu tu você vocês nós isso isto esse essa este esta aquilo mas mais muito muita
    como quando onde porque porquê sobre até já não sim foi era tem ter vai ser são
    """.split()
)


def _plain(text: str) -> str:
    decomposed = unicodedata.normalize("NFKD", text.lower())
    return "".join(c for c in decomposed if not unicodedata.combining(c))


def _matches(word: str, wanted: str) -> bool:
    return _plain(word) == _plain(wanted)


def pick_keyword(title: str, suggested: Optional[str] = None) -> Optional[str]:
    """A palavra de `title` a destacar, escrita como está nele. None sem palavras."""
    words = _WORD.findall(title or "")
    if not words:
        return None

    if suggested:
        pedida = _WORD.findall(suggested)
        if len(pedida) == 1:
            achada = next((w for w in words if _matches(w, pedida[0])), None)
            if achada:
                return achada

    # Número é quase sempre o impacto: "perdi 200 mil seguidores".
    numero = next((w for w in words if any(c.isdigit() for c in w)), None)
    if numero:
        return numero

    candidatas = [w for w in words if _plain(w) not in {_plain(s) for s in _STOPWORDS}]
    return max(candidatas or words, key=len)
