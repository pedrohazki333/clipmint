"""
Registro dos provedores de transcrição.

Quem escolhe é `TRANSCRIPTION_PROVIDER` no .env. O padrão é o AssemblyAI, e
mudar isso é uma decisão a ser tomada com o relatório do modo de comparação na
mão (`python -m app.scripts.compare_transcribers`), não por impressão.
"""

from app.config import settings
from app.services.transcription.assemblyai import AssemblyAIProvider
from app.services.transcription.base import (
    ProviderTranscript,
    TranscriptionProvider,
    TranscriptionResult,
    WordTimestamp,
)
from app.services.transcription.deepgram import DeepgramProvider

#: Nome no .env → classe. Acrescentar provedor é acrescentar uma linha aqui.
PROVIDERS: dict[str, type[TranscriptionProvider]] = {
    AssemblyAIProvider.name: AssemblyAIProvider,
    DeepgramProvider.name: DeepgramProvider,
}

DEFAULT_PROVIDER = AssemblyAIProvider.name


def get_provider(name: str | None = None) -> TranscriptionProvider:
    """O provedor pedido, ou o configurado no .env."""
    escolhido = (name or settings.transcription_provider or DEFAULT_PROVIDER).lower()
    if escolhido not in PROVIDERS:
        conhecidos = ", ".join(sorted(PROVIDERS))
        raise ValueError(
            f"Provedor de transcrição desconhecido: {escolhido!r}. "
            f"Conhecidos: {conhecidos}."
        )
    return PROVIDERS[escolhido]()


__all__ = [
    "DEFAULT_PROVIDER",
    "PROVIDERS",
    "ProviderTranscript",
    "TranscriptionProvider",
    "TranscriptionResult",
    "WordTimestamp",
    "get_provider",
]
