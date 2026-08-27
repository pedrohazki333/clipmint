"""
O provedor Deepgram, testado sem chave de API.

Não dá para chamar a API de verdade aqui, e é justamente por isso que estes
testes existem: se a requisição ou o parsing estiverem errados, o erro só
apareceria no dia em que alguém plugasse a chave para decidir a troca — e
pareceria defeito do Deepgram, não nosso.

A resposta usada é a forma documentada da API de pré-gravado: results →
channels → alternatives → words, com `punctuated_word` ao lado de `word`.
"""

import asyncio
import json

import httpx
import pytest

from app.config import settings
from app.services.transcription import deepgram as dg
from app.services.transcription.deepgram import DeepgramProvider

RESPOSTA = {
    "metadata": {"duration": 37.2, "channels": 1, "models": ["nova-3"]},
    "results": {
        "channels": [
            {
                "detected_language": "pt",
                "alternatives": [
                    {
                        "transcript": "Calma, calma, vai! Segura ele, papai!",
                        "confidence": 0.98,
                        "words": [
                            {"word": "calma", "punctuated_word": "Calma,",
                             "start": 0.08, "end": 0.44, "confidence": 0.99},
                            {"word": "calma", "punctuated_word": "calma,",
                             "start": 0.44, "end": 0.80, "confidence": 0.97},
                            {"word": "vai", "punctuated_word": "vai!",
                             "start": 0.80, "end": 1.12, "confidence": 0.88},
                            {"word": "segura", "punctuated_word": "Segura",
                             "start": 1.30, "end": 1.70, "confidence": 0.61},
                        ],
                    }
                ],
            }
        ]
    },
}


@pytest.fixture(autouse=True)
def chave(monkeypatch):
    monkeypatch.setattr(settings, "deepgram_api_key", "chave-de-teste")
    monkeypatch.setattr(settings, "deepgram_model", "nova-3")
    monkeypatch.setattr(settings, "deepgram_language", "pt")


@pytest.fixture
def audio(tmp_path):
    p = tmp_path / "audio.wav"
    p.write_bytes(b"RIFF" + b"\0" * 4096)
    return str(p)


def _transcrever_com(monkeypatch, audio, handler):
    """Roda transcribe() contra um transporte httpx falso, e devolve o resultado."""
    capturado = {}

    def wrapper(request: httpx.Request) -> httpx.Response:
        capturado["request"] = request
        return handler(request)

    transport = httpx.MockTransport(wrapper)
    original = httpx.AsyncClient

    class ClientFalso(original):
        def __init__(self, *a, **kw):
            kw["transport"] = transport
            super().__init__(*a, **kw)

    monkeypatch.setattr(dg.httpx, "AsyncClient", ClientFalso)
    resultado = asyncio.run(DeepgramProvider().transcribe("job1", audio))
    return resultado, capturado["request"]


def test_requisicao_pede_canal_unico_e_o_modelo_certo(monkeypatch, audio):
    """multichannel=false é o que evita pagar por dois canais."""
    _, req = _transcrever_com(
        monkeypatch, audio, lambda r: httpx.Response(200, json=RESPOSTA)
    )

    assert req.url.host == "api.deepgram.com"
    params = dict(req.url.params)
    assert params["multichannel"] == "false"
    assert params["model"] == "nova-3"
    assert params["language"] == "pt"
    assert params["punctuate"] == "true"
    assert req.headers["authorization"] == "Token chave-de-teste"
    assert req.headers["content-type"] == "audio/wav"


def test_sem_idioma_configurado_pede_deteccao(monkeypatch, audio):
    monkeypatch.setattr(settings, "deepgram_language", "")
    _, req = _transcrever_com(
        monkeypatch, audio, lambda r: httpx.Response(200, json=RESPOSTA)
    )
    params = dict(req.url.params)
    assert params["detect_language"] == "true"
    assert "language" not in params


def test_palavras_vem_com_pontuacao(monkeypatch, audio):
    """
    `punctuated_word`, não `word`.

    A legenda usa este texto: com a palavra crua ela sairia sem vírgula nem
    maiúscula, e o karaokê ficaria um bloco sem respiro.
    """
    r, _ = _transcrever_com(
        monkeypatch, audio, lambda req: httpx.Response(200, json=RESPOSTA)
    )
    assert [w.text for w in r.words] == ["Calma,", "calma,", "vai!", "Segura"]
    assert r.words[0].start == pytest.approx(0.08)
    assert r.words[0].end == pytest.approx(0.44)
    assert r.words[3].confidence == pytest.approx(0.61)
    assert r.full_text.startswith("Calma, calma, vai!")
    assert r.language == "pt"
    assert r.model == "nova-3"


def test_audio_sem_fala_devolve_vazio_sem_estourar(monkeypatch, audio):
    """Vídeo só com música é caso real, não hipótese."""
    vazio = {"metadata": {}, "results": {"channels": [{"alternatives": []}]}}
    r, _ = _transcrever_com(
        monkeypatch, audio, lambda req: httpx.Response(200, json=vazio)
    )
    assert r.words == []
    assert r.full_text == ""


def test_erro_http_vira_mensagem_com_o_codigo(monkeypatch, audio):
    with pytest.raises(RuntimeError, match="HTTP 401"):
        _transcrever_com(
            monkeypatch,
            audio,
            lambda req: httpx.Response(401, text="Invalid credentials"),
        )


def test_audio_ausente_falha_antes_de_gastar_chamada(monkeypatch):
    with pytest.raises(RuntimeError, match="não encontrado"):
        asyncio.run(DeepgramProvider().transcribe("job1", "/nao/existe.wav"))


def test_sem_chave_recusa_antes_de_chamar(monkeypatch, audio):
    monkeypatch.setattr(settings, "deepgram_api_key", "")
    with pytest.raises(RuntimeError, match="não tem chave de API"):
        asyncio.run(DeepgramProvider().transcribe("job1", audio))


def test_custo_usa_a_tarifa_configurada(monkeypatch):
    monkeypatch.setattr(settings, "deepgram_cost_per_hour", 0.258)
    assert DeepgramProvider().estimate_cost_usd(3600.0) == pytest.approx(0.258)
    assert DeepgramProvider().estimate_cost_usd(1800.0) == pytest.approx(0.129)
