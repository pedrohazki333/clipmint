"""
Modo de comparação: o mesmo áudio pelos dois provedores, lado a lado.

Serve para UMA decisão — trocar ou não o provedor padrão — e por isso mede o
que decide essa troca neste projeto, não métricas genéricas de benchmark. Os
três defeitos abaixo são os que já apareceram em material real e estão
registrados em config.py:

  - **alucinação em fala difícil**: num trecho de grito distorcido o
    universal-2 inventou "TREADOR!" e 46% das palavras ficaram abaixo de 0,7 de
    confiança (contra 9% do universal-3-5-pro). Daí a fração de baixa confiança;
  - **loop do decodificador**: o universal-3-5-pro travou repetindo "não" 128 e
    121 vezes, e um dos loops comeu a fala que estava ali. Daí a maior sequência
    repetida;
  - **palavra sem duração própria**: um terço das palavras do universal-3-pro
    saiu com duração ~zero, o que estraga a legenda karaokê. Daí a fração
    degenerada.

As medições são feitas no texto BRUTO do provedor, antes da limpeza da fachada.
Medir depois compararia o pós-processamento, não os modelos.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import List

from app.services.transcription.base import ProviderTranscript, WordTimestamp
from app.services.transcription.postprocess import drop_degenerate_repeats

#: Abaixo disto a palavra é "duvidosa". Mesmo corte usado nas medições que estão
#: documentadas em config.py, para os números serem comparáveis com aqueles.
LOW_CONFIDENCE = 0.7

#: Palavra que não ocupa tempo nenhum. Fala real, mesmo rápida, não cabe em 20ms.
DEGENERATE_MAX_DURATION = 0.02


def longest_repeat_run(words: List[WordTimestamp]) -> tuple[str, int]:
    """A maior sequência da MESMA palavra repetida em seguida."""
    melhor_texto, melhor = "", 0
    atual_texto, atual = "", 0
    for w in words:
        texto = w.text.strip().lower()
        if texto == atual_texto:
            atual += 1
        else:
            atual_texto, atual = texto, 1
        if atual > melhor:
            melhor_texto, melhor = atual_texto, atual
    return melhor_texto, melhor


@dataclass
class ProviderRun:
    """O resultado de um provedor mais tudo que se mediu dele."""

    provider: str
    model: str
    ok: bool
    #: Tempo de parede da chamada, em segundos.
    elapsed: float = 0.0
    cost_usd: float = 0.0
    error: str = ""
    full_text: str = ""
    words: List[WordTimestamp] = field(default_factory=list)
    language: str | None = None

    # ── Métricas ─────────────────────────────────────────────────────────────
    word_count: int = 0
    avg_confidence: float = 0.0
    low_confidence_frac: float = 0.0
    degenerate_frac: float = 0.0
    longest_repeat_word: str = ""
    longest_repeat_len: int = 0
    #: Quantas palavras a limpeza da fachada removeria deste texto bruto.
    would_drop: int = 0

    def measure(self) -> None:
        w = self.words
        self.word_count = len(w)
        if not w:
            return
        self.avg_confidence = sum(x.confidence for x in w) / len(w)
        self.low_confidence_frac = sum(
            1 for x in w if x.confidence < LOW_CONFIDENCE
        ) / len(w)
        self.degenerate_frac = sum(
            1 for x in w if (x.end - x.start) <= DEGENERATE_MAX_DURATION
        ) / len(w)
        self.longest_repeat_word, self.longest_repeat_len = longest_repeat_run(w)
        _, self.would_drop = drop_degenerate_repeats(w)


async def run_provider(provider, job_id: str, audio_path: str, duration: float) -> ProviderRun:
    """Roda um provedor medindo tempo e custo, sem deixar a falha derrubar o resto.

    Uma falha vira uma linha de erro no relatório em vez de interromper a
    comparação: saber que um provedor recusou o arquivo TAMBÉM é resultado.
    """
    inicio = time.monotonic()
    try:
        transcript: ProviderTranscript = await provider.transcribe(job_id, audio_path)
    except Exception as exc:  # noqa: BLE001 - a falha é dado, não acidente
        return ProviderRun(
            provider=provider.name,
            model="",
            ok=False,
            elapsed=time.monotonic() - inicio,
            error=f"{type(exc).__name__}: {exc}",
        )

    run = ProviderRun(
        provider=provider.name,
        model=transcript.model,
        ok=True,
        elapsed=time.monotonic() - inicio,
        cost_usd=provider.estimate_cost_usd(duration),
        full_text=transcript.full_text,
        words=transcript.words,
        language=transcript.language,
    )
    run.measure()
    return run


def render_report(runs: List[ProviderRun], audio_path: str, duration: float) -> str:
    """O relatório em markdown, para ler no terminal e guardar em arquivo."""
    linhas: List[str] = []
    linhas.append("# Comparação de provedores de transcrição\n")
    linhas.append(f"- **Áudio:** `{audio_path}`")
    linhas.append(f"- **Duração:** {duration / 60:.1f} min ({duration:.0f}s)\n")

    ok = [r for r in runs if r.ok]
    falhas = [r for r in runs if not r.ok]

    if falhas:
        linhas.append("## Falhas\n")
        for r in falhas:
            linhas.append(f"- **{r.provider}**: {r.error}")
        linhas.append("")

    if not ok:
        linhas.append("_Nenhum provedor respondeu — não há o que comparar._")
        return "\n".join(linhas)

    cab = " | ".join(r.provider for r in ok)
    sep = " | ".join("---" for _ in ok)
    linhas.append("## Números\n")
    linhas.append(f"| Medida | {cab} |")
    linhas.append(f"|---|{sep}|")

    def linha(rotulo: str, fn) -> None:
        linhas.append(f"| {rotulo} | " + " | ".join(fn(r) for r in ok) + " |")

    linha("Modelo", lambda r: f"`{r.model}`")
    linha("Idioma detectado", lambda r: str(r.language or "—"))
    linha("Tempo de processamento", lambda r: f"{r.elapsed:.1f}s")
    linha(
        "Velocidade",
        lambda r: f"{duration / r.elapsed:.1f}x tempo real" if r.elapsed else "—",
    )
    linha("Custo estimado", lambda r: f"US$ {r.cost_usd:.4f}")
    linha("Custo por hora de áudio", lambda r: f"US$ {r.cost_usd / (duration / 3600):.3f}" if duration else "—")
    linha("Palavras", lambda r: f"{r.word_count:,}".replace(",", "."))
    linha("Confiança média", lambda r: f"{r.avg_confidence:.3f}")
    linha(
        f"Palavras abaixo de {LOW_CONFIDENCE}",
        lambda r: f"{r.low_confidence_frac:.1%}",
    )
    linha("Palavras sem duração própria", lambda r: f"{r.degenerate_frac:.1%}")
    linha(
        "Maior repetição seguida",
        lambda r: (
            f"{r.longest_repeat_len}x {r.longest_repeat_word!r}"
            if r.longest_repeat_len > 1
            else "—"
        ),
    )
    linha("Palavras que a limpeza removeria", lambda r: str(r.would_drop))

    linhas.append("\n### Como ler\n")
    linhas.append(
        "- **Palavras abaixo do corte de confiança** é o sinal de alucinação em "
        "fala difícil: no trecho que motivou a troca de modelo, o ruim deu 46% "
        "e o bom deu 9%."
    )
    linhas.append(
        "- **Maior repetição seguida** é o sinal de loop do decodificador. "
        "Acima de ~6 é defeito, não ênfase — e o loop costuma comer a fala que "
        "estava ali."
    )
    linhas.append(
        "- **Palavras sem duração própria** estragam a legenda karaokê, que "
        "precisa do tempo de cada palavra para acender uma de cada vez."
    )
    linhas.append(
        "- **Custo** é estimativa pela tabela pay-as-you-go em config.py, não "
        "a fatura. Confira se o preço mudou antes de decidir por ele."
    )

    linhas.append("\n## Texto transcrito\n")
    for r in ok:
        linhas.append(f"### {r.provider} (`{r.model}`)\n")
        linhas.append("```")
        linhas.append(r.full_text.strip() or "(vazio)")
        linhas.append("```\n")

    return "\n".join(linhas)
