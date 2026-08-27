"""
O teto do upload tem que valer DURANTE a leitura, não depois dela.

A versão anterior fazia `data = await clip.read()` e só então comparava com os
500MB. O teto não protegia de nada: um upload de 2GB já estava inteiro na
memória do processo quando era recusado. Num VPS pequeno com mais de um
usuário, é o caminho mais curto para o OOM.

Estes testes provam que a leitura PARA no pedaço em que o limite estoura, e que
nenhum arquivo temporário fica para trás em nenhum dos desfechos.
"""

import asyncio

import pytest
from fastapi import HTTPException

from app.config import settings
from app.routers import references


class UploadFalso:
    """UploadFile o bastante para o _stage_clip, contando o que foi entregue."""

    def __init__(self, filename: str, total: int, chunk: int = 1024 * 1024):
        self.filename = filename
        self._restante = total
        self._chunk = chunk
        self.bytes_entregues = 0

    async def read(self, size: int = -1) -> bytes:
        if self._restante <= 0:
            return b""
        n = min(size if size > 0 else self._chunk, self._restante, self._chunk)
        self._restante -= n
        self.bytes_entregues += n
        return b"\0" * n


@pytest.fixture(autouse=True)
def storage_isolado(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "storage_dir", str(tmp_path))
    settings.ensure_dirs()
    return tmp_path


def _temporarios() -> list:
    return list(settings.references_dir.iterdir())


def test_para_de_ler_assim_que_estoura_o_teto(monkeypatch):
    """O corpo restante não é lido nem gravado."""
    monkeypatch.setattr(references, "_MAX_CLIP_BYTES", 3 * 1024 * 1024)  # 3MB
    upload = UploadFalso("grande.mp4", total=200 * 1024 * 1024)  # 200MB oferecidos

    with pytest.raises(HTTPException) as exc:
        asyncio.run(references._stage_clip(upload))

    assert exc.value.status_code == 413
    # Leu só até o pedaço que estourou (3MB + 1 pedaço de folga), não os 200MB.
    assert upload.bytes_entregues <= 5 * 1024 * 1024, (
        f"leu {upload.bytes_entregues / 1e6:.0f}MB antes de recusar — "
        f"o teto voltou a valer só depois da leitura"
    )
    assert _temporarios() == [], "sobrou arquivo temporário depois da recusa"


def test_arquivo_vazio_e_recusado_sem_deixar_sobra():
    upload = UploadFalso("vazio.mp4", total=0)
    with pytest.raises(HTTPException) as exc:
        asyncio.run(references._stage_clip(upload))
    assert exc.value.status_code == 422
    assert _temporarios() == []


def test_formato_invalido_nao_chega_a_criar_arquivo():
    upload = UploadFalso("planilha.xlsx", total=1024)
    with pytest.raises(HTTPException) as exc:
        asyncio.run(references._stage_clip(upload))
    assert exc.value.status_code == 422
    assert _temporarios() == []


def test_upload_valido_fica_em_disco_com_o_tamanho_certo():
    upload = UploadFalso("ok.mp4", total=5 * 1024 * 1024)
    staged, ext = asyncio.run(references._stage_clip(upload))
    assert ext == ".mp4"
    assert staged.exists()
    assert staged.stat().st_size == 5 * 1024 * 1024
    assert upload.bytes_entregues == 5 * 1024 * 1024
