"""
Contrato comum dos provedores de transcrição.

O pipeline não conhece AssemblyAI nem Deepgram: ele pede uma transcrição com
timestamps por palavra e recebe sempre a mesma forma. Trocar de provedor é
trocar uma variável de ambiente, e comparar os dois é rodar os dois contra o
mesmo arquivo.

O que NÃO fica aqui, de propósito:

  - o pós-processamento (repetições degeneradas): é defeito de decodificador e
    aparece nos dois provedores, então vale para todo mundo e mora no
    `postprocess.py`, aplicado pela fachada;
  - a gravação do JSON de palavras: é artefato do pipeline, não do provedor.

Assim um provedor novo só precisa saber falar com a API dele.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import List, Optional


@dataclass
class WordTimestamp:
    text: str
    start: float  # segundos
    end: float    # segundos
    confidence: float


@dataclass
class ProviderTranscript:
    """O que um provedor devolve, antes do pós-processamento comum."""

    full_text: str
    words: List[WordTimestamp]
    language: Optional[str]
    #: Nome do modelo que realmente rodou, como o provedor o reporta. Vai para o
    #: relatório de comparação: "universal-3-pro" e "nova-3" não são
    #: intercambiáveis e o relatório tem que dizer o que foi medido.
    model: str = ""
    #: Qualquer coisa que só aquele provedor informe (duração cobrada, etc.).
    extra: dict = field(default_factory=dict)


@dataclass
class TranscriptionResult:
    """O que o pipeline consome."""

    full_text: str
    words: List[WordTimestamp]
    words_json_path: str
    language: Optional[str]
    confidence: float
    #: Provedor que produziu esta transcrição ("assemblyai" | "deepgram").
    provider: str = ""
    model: str = ""


class TranscriptionProvider(ABC):
    """Um serviço de transcrição com timestamps por palavra."""

    #: Nome curto usado em TRANSCRIPTION_PROVIDER e nos logs.
    name: str = ""

    @abstractmethod
    async def transcribe(self, job_id: str, audio_path: str) -> ProviderTranscript:
        """Transcreve o arquivo. Levanta RuntimeError se o serviço falhar."""

    @abstractmethod
    def estimate_cost_usd(self, duration_seconds: float) -> float:
        """Quanto esta transcrição custou, em dólares, pela tabela publicada."""

    @abstractmethod
    def is_configured(self) -> bool:
        """Há chave de API para usar este provedor?"""

    def require_configured(self) -> None:
        if not self.is_configured():
            raise RuntimeError(
                f"O provedor de transcrição '{self.name}' não tem chave de API "
                f"configurada no .env."
            )
