"""
A transcrição atrás de uma interface única, e a comparação que decide a troca.

Três coisas precisam ficar guardadas:

  1. o pipeline continua chamando `transcribe_audio` e não sabe qual serviço
     respondeu — trocar de provedor é trocar uma variável de ambiente;
  2. a limpeza de repetições degeneradas vale para QUALQUER provedor. Se ela
     ficasse dentro de um deles, a comparação mediria o pós-processamento em vez
     dos modelos;
  3. as métricas da comparação medem os defeitos reais que este projeto já
     encontrou (ver services/transcription/compare.py), e não números genéricos.
"""

import asyncio
import json

import pytest

from app.config import settings
from app.services import transcriber
from app.services.transcription import PROVIDERS, get_provider
from app.services.transcription.base import (
    ProviderTranscript,
    TranscriptionProvider,
    WordTimestamp,
)
from app.services.transcription.compare import (
    ProviderRun,
    longest_repeat_run,
    render_report,
    run_provider,
)


def palavras(*specs) -> list[WordTimestamp]:
    """(texto, inicio, fim, confianca) → lista de WordTimestamp."""
    return [WordTimestamp(text=t, start=s, end=e, confidence=c) for t, s, e, c in specs]


class ProvedorFalso(TranscriptionProvider):
    name = "falso"

    def __init__(self, words=None, texto="oi tudo bem", falha=None):
        self._words = words if words is not None else palavras(
            ("oi", 0.0, 0.4, 0.9), ("tudo", 0.4, 0.8, 0.8), ("bem", 0.8, 1.2, 0.95)
        )
        self._texto = texto
        self._falha = falha

    def is_configured(self) -> bool:
        return True

    async def transcribe(self, job_id, audio_path):
        if self._falha:
            raise RuntimeError(self._falha)
        return ProviderTranscript(
            full_text=self._texto, words=self._words, language="pt", model="modelo-x"
        )

    def estimate_cost_usd(self, duration_seconds: float) -> float:
        return duration_seconds / 3600.0 * 1.0


@pytest.fixture(autouse=True)
def storage(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "storage_dir", str(tmp_path))
    settings.ensure_dirs()
    return tmp_path


# ─── Registro e seleção ────────────────────────────────────────────────────────

def test_os_dois_provedores_estao_registrados():
    assert set(PROVIDERS) == {"assemblyai", "deepgram"}


def test_padrao_continua_sendo_assemblyai(monkeypatch):
    """A troca do padrão é decisão do dono do projeto, não efeito colateral."""
    monkeypatch.setattr(settings, "transcription_provider", "assemblyai")
    assert get_provider().name == "assemblyai"


def test_provedor_escolhido_por_configuracao(monkeypatch):
    monkeypatch.setattr(settings, "transcription_provider", "deepgram")
    assert get_provider().name == "deepgram"


def test_provedor_desconhecido_falha_dizendo_os_conhecidos(monkeypatch):
    monkeypatch.setattr(settings, "transcription_provider", "whisper")
    with pytest.raises(ValueError, match="assemblyai, deepgram"):
        get_provider()


def test_provedor_sem_chave_recusa_com_mensagem_util(monkeypatch):
    monkeypatch.setattr(settings, "deepgram_api_key", "")
    p = get_provider("deepgram")
    assert not p.is_configured()
    with pytest.raises(RuntimeError, match="não tem chave de API"):
        p.require_configured()


# ─── A fachada é agnóstica ─────────────────────────────────────────────────────

def test_fachada_devolve_o_mesmo_formato_seja_qual_for_o_provedor(monkeypatch):
    monkeypatch.setattr(transcriber, "get_provider", lambda nome=None: ProvedorFalso())

    r = asyncio.run(transcriber.transcribe_audio("job1", "/nao/importa.wav"))

    assert r.full_text == "oi tudo bem"
    assert len(r.words) == 3
    assert r.provider == "falso"
    assert r.model == "modelo-x"
    assert r.language == "pt"
    assert 0.88 < r.confidence < 0.89  # média das confianças
    # O JSON de palavras é artefato do pipeline e sai igual para todo provedor.
    salvo = json.loads(open(r.words_json_path, encoding="utf-8").read())
    assert [w["text"] for w in salvo] == ["oi", "tudo", "bem"]


def test_limpeza_de_loop_vale_para_qualquer_provedor(monkeypatch):
    """
    O defeito é do decodificador, não do fornecedor.

    Deixá-la dentro de um provedor faria a comparação medir pós-processamento.
    """
    loop = palavras(*[("não", 5.0, 5.0, 1.0) for _ in range(40)])
    monkeypatch.setattr(
        transcriber, "get_provider", lambda nome=None: ProvedorFalso(words=loop)
    )

    r = asyncio.run(transcriber.transcribe_audio("job2", "/x.wav"))
    assert len(r.words) < 40, "a limpeza não rodou sobre o provedor genérico"


def test_destino_do_json_pode_ser_escolhido(tmp_path, monkeypatch):
    """A comparação precisa disso: dois provedores não podem escrever no mesmo."""
    monkeypatch.setattr(transcriber, "get_provider", lambda nome=None: ProvedorFalso())
    destino = tmp_path / "meu_words.json"
    r = asyncio.run(
        transcriber.transcribe_audio("job3", "/x.wav", words_json_path=str(destino))
    )
    assert r.words_json_path == str(destino)
    assert destino.is_file()


# ─── Métricas da comparação ────────────────────────────────────────────────────

def test_maior_repeticao_seguida():
    ws = palavras(
        ("a", 0, 1, 1.0), ("não", 1, 2, 1.0), ("não", 2, 3, 1.0),
        ("não", 3, 4, 1.0), ("b", 4, 5, 1.0), ("c", 5, 6, 1.0),
    )
    assert longest_repeat_run(ws) == ("não", 3)


def test_metricas_medem_os_defeitos_documentados():
    """Baixa confiança, palavra sem duração e loop — os três de config.py."""
    ws = palavras(
        ("clara", 0.0, 0.5, 0.95),
        ("duvidosa", 0.5, 1.0, 0.30),          # abaixo de 0.7
        ("colada", 1.0, 1.005, 0.99),          # sem duração própria
        ("não", 2.0, 2.4, 1.0),
        ("não", 2.4, 2.8, 1.0),
    )
    run = ProviderRun(provider="p", model="m", ok=True, words=ws)
    run.measure()

    assert run.word_count == 5
    assert run.low_confidence_frac == pytest.approx(1 / 5)
    assert run.degenerate_frac == pytest.approx(1 / 5)
    assert run.longest_repeat_len == 2


def test_falha_de_um_provedor_nao_derruba_a_comparacao():
    """Saber que um provedor recusou o arquivo TAMBÉM é resultado."""
    run = asyncio.run(
        run_provider(ProvedorFalso(falha="cota estourada"), "j", "/a.wav", 600.0)
    )
    assert not run.ok
    assert "cota estourada" in run.error
    assert run.elapsed >= 0


def test_custo_e_proporcional_a_duracao():
    p = ProvedorFalso()
    assert p.estimate_cost_usd(3600.0) == pytest.approx(1.0)
    assert p.estimate_cost_usd(1800.0) == pytest.approx(0.5)


def test_relatorio_traz_texto_tempo_e_custo():
    """Os três itens que a comparação tem que entregar."""
    run = asyncio.run(run_provider(ProvedorFalso(), "j", "/a.wav", 3600.0))
    texto = render_report([run], "/a.wav", 3600.0)

    assert "oi tudo bem" in texto            # (a) o texto transcrito
    assert "Tempo de processamento" in texto  # (b) o tempo
    assert "US$ 1.0000" in texto              # (c) o custo estimado
    assert "modelo-x" in texto


def test_relatorio_registra_provedor_que_falhou():
    run = asyncio.run(run_provider(ProvedorFalso(falha="503"), "j", "/a.wav", 60.0))
    texto = render_report([run], "/a.wav", 60.0)
    assert "Falhas" in texto and "503" in texto


def test_o_timeout_http_do_assemblyai_sai_do_padrao_apertado(monkeypatch):
    """30s (o padrão do SDK) derruba vídeo longo, e a mensagem esconde a causa.

    O timeout do SDK vale para TODA requisição: o envio do áudio e cada consulta
    do polling. Medido em 02/09/2026: enviar 249 MB levou 21s — nove segundos de
    margem. Com o teto de 180 min o áudio passa de 340 MB, e a transcrição fica
    minutos em polling, onde UMA resposta lenta mata o trabalho inteiro.

    Foi o que derrubou o job de 130 min: morreu aos 15,5 min sem nunca ter
    chegado à fila da AssemblyAI, exibindo a mensagem GENÉRICA — um timeout do
    `requests` não diz "assemblyai error" e não casa com a tradução de erro.
    """
    import assemblyai as aai

    from app.services.transcription.assemblyai import AssemblyAIProvider

    monkeypatch.setattr(settings, "assemblyai_api_key", "chave-de-teste")
    monkeypatch.setattr(settings, "assemblyai_http_timeout", 300.0)
    monkeypatch.setattr(aai.settings, "http_timeout", 30.0)

    class _Falso:
        status = "completed"
        error = None
        words = []
        text = ""
        json_response = {}

    monkeypatch.setattr(
        aai.Transcriber, "transcribe", lambda self, path, **kw: _Falso()
    )

    asyncio.run(AssemblyAIProvider().transcribe("j1", "/tmp/a.wav"))

    assert aai.settings.http_timeout == 300.0, "o provedor não afrouxou o timeout"
