"""
Alinhamento de transcrições: localiza onde um clipe foi cortado dentro do vídeo
original.

O clipe viral de outro criador e o vídeo-fonte são o MESMO áudio no trecho
sobreposto, então as duas transcrições do AssemblyAI ficam quase idênticas ali.
Casamos os streams de palavras (normalizadas) e recuperamos o intervalo
[source_start, source_end] em coordenadas do vídeo original.

Robustez:
  - Intro/outro adicionados ao clipe (vinheta, marca do canal) não casam com o
    original e caem fora naturalmente — o span cobre apenas os blocos casados.
  - Blocos de palavras comuns casados longe do trecho real (deslocamento
    clip→source incompatível com o bloco âncora) são descartados como outliers —
    sem isso, um par espúrio esticava o span (ex.: 41 min para um clipe de 1 min).
  - `confidence` = fração dos tokens do clipe que encontraram correspondência.
    Alinhamentos de baixa confiança devem ser revisados/ajustados pelo usuário.
"""

import difflib
import logging
import re
import unicodedata
from dataclasses import dataclass
from typing import List, Optional

logger = logging.getLogger(__name__)

_NON_ALNUM = re.compile(r"[^a-z0-9]")


@dataclass
class AlignmentResult:
    source_start: float
    source_end: float
    confidence: float          # 0.0–1.0 — fração de tokens do clipe casados
    matched_tokens: int
    clip_tokens: int


def _normalize(text: str) -> str:
    """Minúsculas, sem acentos e sem pontuação — para casar apesar de variações do ASR."""
    text = unicodedata.normalize("NFKD", text)
    text = "".join(c for c in text if not unicodedata.combining(c))
    return _NON_ALNUM.sub("", text.lower())


def _tokenize(words: List[dict]) -> tuple[list[str], list[int]]:
    """
    Converte a lista de palavras em tokens normalizados.

    Retorna (tokens, idx_map) onde tokens[k] corresponde a words[idx_map[k]].
    Palavras que normalizam para string vazia (pura pontuação) são descartadas,
    mas o mapeamento de índices para a lista original é preservado.
    """
    tokens: list[str] = []
    idx_map: list[int] = []
    for i, w in enumerate(words):
        t = _normalize(w.get("text", ""))
        if t:
            tokens.append(t)
            idx_map.append(i)
    return tokens, idx_map


def align_clip_to_source(
    clip_words: List[dict],
    source_words: List[dict],
    min_block: int = 2,
) -> Optional[AlignmentResult]:
    """
    Localiza o clipe dentro do vídeo original.

    Args:
        clip_words: palavras (text/start/end) transcritas do clipe viral.
        source_words: palavras (text/start/end) transcritas do vídeo original.
        min_block: tamanho mínimo (em tokens) de um bloco casado para contar —
                   filtra coincidências espúrias de palavras comuns isoladas.

    Returns:
        AlignmentResult com o intervalo no original e a confiança, ou None se
        não houver material suficiente para alinhar.
    """
    src_tokens, src_idx_map = _tokenize(source_words)
    clip_tokens, _ = _tokenize(clip_words)

    if not src_tokens or not clip_tokens:
        logger.warning("Alignment aborted: empty token stream (src=%d, clip=%d)",
                       len(src_tokens), len(clip_tokens))
        return None

    # autojunk=False: em vídeos longos, palavras comuns seriam tratadas como
    # "junk" e ignoradas — aqui queremos casar tudo.
    matcher = difflib.SequenceMatcher(a=src_tokens, b=clip_tokens, autojunk=False)

    blocks = [b for b in matcher.get_matching_blocks() if b.size >= min_block]

    # Fallback: clipes muito curtos podem não ter blocos de tamanho >= min_block.
    if not blocks and min_block > 1:
        blocks = [b for b in matcher.get_matching_blocks() if b.size >= 1]

    if not blocks:
        logger.warning("Alignment failed: no matching blocks between clip and source")
        return None

    # Blocos genuínos mapeiam clip→source com deslocamento (a - b) ~constante,
    # a menos de pequenas inserções/deleções do ASR. Um bloco de palavras comuns
    # casado longe do trecho real tem deslocamento muito diferente do âncora
    # (maior bloco) e esticaria o span — descartamos esses outliers.
    anchor = max(blocks, key=lambda b: b.size)
    anchor_offset = anchor.a - anchor.b
    tolerance = max(50, 2 * len(clip_tokens))
    kept = [b for b in blocks if abs((b.a - b.b) - anchor_offset) <= tolerance]
    if len(kept) < len(blocks):
        logger.info(
            "Alignment dropped %d outlier block(s) incompatible with anchor",
            len(blocks) - len(kept),
        )
    blocks = kept

    first, last = blocks[0], blocks[-1]
    src_start_tok = first.a
    src_end_tok = last.a + last.size - 1

    w_start = src_idx_map[src_start_tok]
    w_end = src_idx_map[src_end_tok]

    matched = sum(b.size for b in blocks)
    confidence = matched / len(clip_tokens)

    source_start = float(source_words[w_start]["start"])
    source_end = float(source_words[w_end]["end"])

    logger.info(
        "Aligned clip → source [%.1f-%.1f]s | matched %d/%d tokens (confidence %.2f)",
        source_start, source_end, matched, len(clip_tokens), confidence,
    )

    return AlignmentResult(
        source_start=source_start,
        source_end=source_end,
        confidence=round(confidence, 3),
        matched_tokens=matched,
        clip_tokens=len(clip_tokens),
    )
