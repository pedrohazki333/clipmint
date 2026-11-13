"""A barra de progresso: o que é medido não recua, e o download soma os arquivos."""

import json

from app.services import progress
from app.services.downloader import _FRACAO_BYTES, _ContadorDeBytes


def setup_function():
    progress._estado.clear()


def test_fracao_medida_nao_recua_na_mesma_etapa():
    progress.set_exact("j", "downloading", 0.5)
    progress.set_exact("j", "downloading", 0.3)
    assert progress.snapshot("j", "downloading")["base"] == 0.5


def test_snapshot_so_vale_para_a_etapa_atual():
    progress.set_exact("j", "downloading", 0.5)
    assert progress.snapshot("j", "transcribing") is None
    assert progress.snapshot("outro", "downloading") is None


def test_estimativa_leva_base_span_e_tempo():
    progress.start_estimate("j", "clipping", 0.25, 0.25, 40)
    snap = progress.snapshot("j", "clipping")
    assert snap["base"] == 0.25 and snap["span"] == 0.25
    assert snap["expected_seconds"] == 40
    assert snap["elapsed_seconds"] >= 0


def test_download_soma_video_e_audio_sem_recomecar():
    c = _ContadorDeBytes("j")
    c.formatos({"requested_formats": [{"filesize": 900}, {"filesize": 100}]})

    c.gancho({"status": "downloading", "downloaded_bytes": 450, "total_bytes": 900})
    assert abs(progress.snapshot("j", "downloading")["base"] - _FRACAO_BYTES * 0.45) < 1e-3

    c.gancho({"status": "finished", "downloaded_bytes": 900, "total_bytes": 900})
    c.gancho({"status": "downloading", "downloaded_bytes": 50, "total_bytes": 100})
    assert abs(progress.snapshot("j", "downloading")["base"] - _FRACAO_BYTES * 0.95) < 1e-3


def test_download_sem_tamanho_conhecido_usa_o_do_arquivo():
    c = _ContadorDeBytes("j")
    c.formatos({"requested_formats": [{}, {}]})
    c.gancho({"status": "downloading", "downloaded_bytes": 10, "total_bytes_estimate": 40})
    assert abs(progress.snapshot("j", "downloading")["base"] - _FRACAO_BYTES * 0.25) < 1e-3


def test_historico_ignora_job_retomado():
    log = [
        {"s": "downloading", "at": "2026-01-01T00:00:00+00:00"},
        {"s": "transcribing", "at": "2026-01-01T00:01:00+00:00"},
        {"s": "error", "at": "2026-01-01T00:02:00+00:00"},
        {"s": "transcribing", "at": "2026-01-01T00:03:00+00:00"},
        {"s": "done", "at": "2026-01-01T00:04:00+00:00"},
    ]
    assert progress._duracoes(json.dumps(log)) is None
    assert progress._duracoes(json.dumps(log[:3])) == {"downloading": 60.0, "transcribing": 60.0}
