"""
Testes da conferência de mídia (downloader.ensure_media).

É a barreira que impede a falha mais cara do pipeline: vídeo e áudio que não
descrevem a mesma linha do tempo. Quando isso passa batido, a transcrição é
feita sobre um relógio e os cortes sobre outro — os clips saem do trecho errado
e com a legenda fora de sincronia, depois de já ter pago transcrição e análise.

Caso real (job 0f65bf71, agosto/2026): a mesclagem do yt-dlp foi feita por dois
processos ao mesmo tempo e o áudio do MP4 saiu com ~29 mil pacotes Opus
corrompidos. O container declarava 9556s de vídeo, mas o áudio decodificava só
9473s — 83s a menos, espalhados pelo arquivo.
"""

import asyncio
from pathlib import Path

from app.services import downloader


def _durations(monkeypatch, table):
    """ffprobe falso: caminho → duração."""

    async def fake_get_duration(path):
        if path not in table:
            raise ValueError(f"sem duração: {path}")
        return table[path]

    monkeypatch.setattr(downloader, "get_duration", fake_get_duration)


def _count_extractions(monkeypatch, after_extract=None, table=None):
    """Conta re-extrações de áudio e, opcionalmente, muda a duração resultante."""
    calls = []

    async def fake_extract(job_id, video_path, audio_path):
        calls.append(audio_path)
        Path(audio_path).write_text("x", encoding="utf-8")
        if after_extract is not None and table is not None:
            table[audio_path] = after_extract

    monkeypatch.setattr(downloader, "_extract_audio", fake_extract)
    return calls


def test_accepts_aligned_media(tmp_path, monkeypatch):
    video = tmp_path / "video.mp4"
    audio = tmp_path / "audio.wav"
    video.write_text("x")
    audio.write_text("x")

    # Desvio de milissegundos é o normal num merge são.
    _durations(monkeypatch, {str(video): 9556.021, str(audio): 9556.013})
    extractions = _count_extractions(monkeypatch)

    assert asyncio.run(
        downloader.ensure_media("job", str(video), str(audio), 9556.0)
    ) is True
    assert extractions == []  # áudio bom não é refeito


def test_rejects_media_with_corrupted_audio(tmp_path, monkeypatch):
    """O caso do job 0f65bf71: o áudio dentro do vídeo está quebrado."""
    video = tmp_path / "video.mp4"
    audio = tmp_path / "audio.wav"
    video.write_text("x")
    audio.write_text("x")

    table = {str(video): 9556.021, str(audio): 9473.091}
    _durations(monkeypatch, table)
    # Re-extrair não adianta: o defeito está no MP4, não no WAV.
    extractions = _count_extractions(monkeypatch, after_extract=9473.091, table=table)

    assert asyncio.run(
        downloader.ensure_media("job", str(video), str(audio), 9556.0)
    ) is False
    assert len(extractions) == 1  # tentou o barato antes de condenar o vídeo


def test_reextracts_audio_when_only_the_wav_is_short(tmp_path, monkeypatch):
    """Extração interrompida se resolve sem re-baixar o vídeo inteiro."""
    video = tmp_path / "video.mp4"
    audio = tmp_path / "audio.wav"
    video.write_text("x")
    audio.write_text("x")

    table = {str(video): 9556.021, str(audio): 4000.0}  # WAV cortado no meio
    _durations(monkeypatch, table)
    extractions = _count_extractions(monkeypatch, after_extract=9556.019, table=table)

    assert asyncio.run(
        downloader.ensure_media("job", str(video), str(audio), 9556.0)
    ) is True
    assert len(extractions) == 1


def test_rejects_truncated_download(tmp_path, monkeypatch):
    """Vídeo menor que o do YouTube = download incompleto."""
    video = tmp_path / "video.mp4"
    audio = tmp_path / "audio.wav"
    video.write_text("x")
    audio.write_text("x")

    # Áudio e vídeo batem entre si, mas os dois estão pela metade.
    _durations(monkeypatch, {str(video): 5000.0, str(audio): 5000.0})
    extractions = _count_extractions(monkeypatch)

    assert asyncio.run(
        downloader.ensure_media("job", str(video), str(audio), 9556.0)
    ) is False
    assert extractions == []  # nem chega a mexer no áudio


def test_extracts_audio_when_missing(tmp_path, monkeypatch):
    video = tmp_path / "video.mp4"
    audio = tmp_path / "audio.wav"
    video.write_text("x")  # WAV ainda não existe

    table = {str(video): 120.0}
    _durations(monkeypatch, table)
    extractions = _count_extractions(monkeypatch, after_extract=120.0, table=table)

    assert asyncio.run(
        downloader.ensure_media("job", str(video), str(audio), 120.0)
    ) is True
    assert len(extractions) == 1


def test_rejects_missing_video(tmp_path, monkeypatch):
    video = tmp_path / "sumiu.mp4"
    audio = tmp_path / "audio.wav"
    audio.write_text("x")

    _durations(monkeypatch, {})

    assert asyncio.run(
        downloader.ensure_media("job", str(video), str(audio), 120.0)
    ) is False


def test_accepts_media_without_expected_duration(tmp_path, monkeypatch):
    """Sem duração do YouTube, a checagem áudio↔vídeo ainda vale."""
    video = tmp_path / "video.mp4"
    audio = tmp_path / "audio.wav"
    video.write_text("x")
    audio.write_text("x")

    _durations(monkeypatch, {str(video): 300.0, str(audio): 299.998})
    _count_extractions(monkeypatch)

    assert asyncio.run(
        downloader.ensure_media("job", str(video), str(audio), 0.0)
    ) is True
