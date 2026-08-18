"""
Testes da retentativa de download.

O YouTube derruba download com `HTTP Error 403: Forbidden` de tempos em tempos,
sem nada de errado no vídeo nem na ferramenta — em 18/08/2026 três jobs
morreram assim e o MESMO vídeo baixou inteiro minutos depois. Cada um desses
soluços marcava o job como erro e exigia alguém mandando rodar de novo à mão.

O que estes testes travam: insistir no que passa sozinho, desistir na hora do
que não passa, e nunca ficar preso num laço infinito.
"""

import asyncio

import pytest
import yt_dlp

from app.services import downloader
from app.services.downloader import (
    _DOWNLOAD_ATTEMPTS,
    _download_with_retry,
    _is_permanent,
)


@pytest.fixture(autouse=True)
def _sem_espera(monkeypatch):
    """A escada de espera é real em produção; no teste ela só atrasaria."""
    async def instantaneo(_):
        return None
    monkeypatch.setattr(downloader.asyncio, "sleep", instantaneo)


def _falha(msg):
    return yt_dlp.utils.DownloadError(msg)


def _roda(efeitos, monkeypatch):
    """Executa o download com uma sequência de resultados/erros programada."""
    chamadas = {"n": 0}

    def fake(url, path):
        i = chamadas["n"]
        chamadas["n"] += 1
        efeito = efeitos[i]
        if isinstance(efeito, Exception):
            raise efeito
        return efeito

    monkeypatch.setattr(downloader, "_download_sync", fake)
    try:
        resultado = asyncio.run(_download_with_retry("job", "url", "/v.mp4"))
    except Exception as exc:  # noqa: BLE001 - o teste inspeciona o tipo
        return exc, chamadas["n"]
    return resultado, chamadas["n"]


# ─── O caso que motivou tudo ──────────────────────────────────────────────────

def test_403_transitorio_e_absorvido(monkeypatch):
    """403 numa tentativa, sucesso na seguinte: o job nem fica sabendo."""
    info = {"title": "Psalm 2", "duration": 2145}
    resultado, n = _roda(
        [_falha("ERROR: unable to download video data: HTTP Error 403: Forbidden"), info],
        monkeypatch,
    )

    assert resultado == info
    assert n == 2


def test_insiste_ate_o_teto_e_so_entao_desiste(monkeypatch):
    erro = _falha("ERROR: unable to download video data: HTTP Error 403: Forbidden")
    resultado, n = _roda([erro] * _DOWNLOAD_ATTEMPTS, monkeypatch)

    assert isinstance(resultado, yt_dlp.utils.DownloadError)
    assert n == _DOWNLOAD_ATTEMPTS


def test_sucesso_de_primeira_nao_espera_nada(monkeypatch):
    info = {"title": "ok"}
    resultado, n = _roda([info], monkeypatch)

    assert resultado == info
    assert n == 1


# ─── Erro permanente não vira espera de minutos ───────────────────────────────

@pytest.mark.parametrize("mensagem", [
    "ERROR: [youtube] abc: Video unavailable",
    "ERROR: [youtube] abc: Private video. Sign in if you've been granted access",
    "ERROR: [youtube] abc: This video is DRM protected",
    "ERROR: [youtube] abc: Requested format is not available",
    "ERROR: [youtube] abc: Sign in to confirm your age",
    "ERROR: [youtube] abc: This video is not available in your country",
])
def test_erro_permanente_desiste_na_primeira(mensagem, monkeypatch):
    """
    Insistir aqui só faria o usuário esperar minutos pela mesma resposta, e
    esconderia qual é o problema de verdade.
    """
    resultado, n = _roda([_falha(mensagem)] * _DOWNLOAD_ATTEMPTS, monkeypatch)

    assert isinstance(resultado, yt_dlp.utils.DownloadError)
    assert n == 1, "retentou um erro que nunca vai passar"


@pytest.mark.parametrize("mensagem", [
    "ERROR: unable to download video data: HTTP Error 403: Forbidden",
    "ERROR: Unable to download webpage: HTTP Error 429: Too Many Requests",
    "ERROR: unable to download video data: HTTP Error 500: Internal Server Error",
    "ERROR: [download] Got error: Connection reset by peer",
    "ERROR: fragment 3 not found, unable to continue",
])
def test_erro_transitorio_e_retentado(mensagem, monkeypatch):
    resultado, n = _roda([_falha(mensagem), {"title": "ok"}], monkeypatch)

    assert resultado == {"title": "ok"}
    assert n == 2


# ─── Classificação isolada ────────────────────────────────────────────────────

def test_classificacao_ignora_caixa_alta():
    assert _is_permanent("ERROR: VIDEO UNAVAILABLE")
    assert not _is_permanent("HTTP Error 403: Forbidden")


def test_erro_desconhecido_e_tratado_como_transitorio():
    """
    Na dúvida, insistir: o custo é esperar alguns minutos, e o custo do
    contrário é o job morrer por um soluço que passaria sozinho.
    """
    assert not _is_permanent("ERROR: algo que ninguém viu antes")
