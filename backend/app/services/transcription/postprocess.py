"""
Pós-processamento comum a todos os provedores de transcrição.

Travar numa palavra e cuspir dezenas de cópias é defeito de decodificador, não
de fornecedor: o AssemblyAI fez isso num trecho de grito distorcido (121x "não"
em 20s, todas com confiança ~1.0) e não há razão para supor que o Deepgram seja
imune. Por isso a limpeza fica aqui, aplicada pela fachada depois de qualquer
provedor — e não dentro de um deles.
"""

from typing import List

from app.services.transcription.base import WordTimestamp


#: Duração máxima de uma palavra para ela ser considerada "sem tempo próprio".
#: Fala real, mesmo rápida, não cabe em 20ms.
_DEGENERATE_MAX_DURATION = 0.02

#: Teto de repetições consecutivas da mesma palavra. Alguém grita "não, não,
#: não" — não 121 vezes seguidas. Acima disso a legenda fica ilegível e o
#: analisador lê a repetição como bordão, então o excedente cai mesmo que
#: cada cópia tenha duração própria.
_MAX_CONSECUTIVE_REPEATS = 6


def drop_degenerate_repeats(words: List[WordTimestamp]) -> tuple[List[WordTimestamp], int]:
    """
    Remove repetições que o decodificador cospe em loop num trecho difícil.

    Em grito distorcido com vozes sobrepostas o modelo às vezes trava numa
    palavra e emite dezenas de cópias empilhadas no mesmo instante — 121x
    "não" em 20s, todas com confiança ~1.0. Vira legenda ilegível e engana o
    analisador, que lê a repetição como bordão.

    Dois sinais denunciam a cópia. O primeiro é não ocupar tempo nenhum —
    fala real tem duração própria. O segundo é o tamanho da sequência: parte
    das cópias vem com alguns centésimos de duração e escapa do primeiro
    filtro, então a repetição consecutiva também tem teto.

    Do excedente, ficam as cópias mais longas: são as que têm mais chance de
    corresponder a uma palavra realmente pronunciada.
    """
    kept: List[WordTimestamp] = []
    dropped = 0

    def flush(run: List[WordTimestamp]) -> None:
        nonlocal dropped
        if len(run) <= _MAX_CONSECUTIVE_REPEATS:
            kept.extend(run)
            return
        longest = sorted(run, key=lambda w: w.end - w.start, reverse=True)
        survivors = set(id(w) for w in longest[:_MAX_CONSECUTIVE_REPEATS])
        dropped += len(run) - _MAX_CONSECUTIVE_REPEATS
        kept.extend(w for w in run if id(w) in survivors)  # mantém a ordem

    run: List[WordTimestamp] = []
    for w in words:
        same = run and run[-1].text.strip().lower() == w.text.strip().lower()
        if same and (w.end - w.start) <= _DEGENERATE_MAX_DURATION:
            dropped += 1  # cópia empilhada no mesmo instante
            continue
        if same:
            run.append(w)
            continue
        flush(run)
        run = [w]
    flush(run)
    return kept, dropped
