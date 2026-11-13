"""
A capa enviada pela pessoa, no lugar da que o ClipMint escolhe do clipe.

Só o layout "Capa + faixa" tem capa: o quadro de cima, de 1080 × 800, acima da
faixa do título (ver `cut_cover` em services/clipper.py). A imagem chega antes
de o job existir — a tela manda o arquivo assim que a pessoa o escolhe, e o
pedido de geração leva só o id —, então ela mora primeiro numa área de envios
da própria conta e, quando o job nasce, muda para a pasta dele.

Imagem de outra proporção não é recusada: é recortada pelo centro até encher o
quadro, do mesmo jeito que a tela mostra antes de gerar. Esticar distorceria; e
deixar faixas pretas poria um buraco entre a capa e a faixa.
"""

from __future__ import annotations

import io
import logging
import re
import shutil
import time
from pathlib import Path

from PIL import Image, ImageOps, UnidentifiedImageError

from app.config import settings
from app.models import uuid4_hex
from app.services.title_card import BAND_Y

logger = logging.getLogger(__name__)

#: O quadro da capa no clipe 1080 × 1920: a largura toda, do topo até a faixa.
COVER_W, COVER_H = 1080, BAND_Y

MAX_BYTES = 10 * 1024 * 1024
#: Envio que nenhum job usou some depois disto (a faxina passa a cada 6 h).
VALIDADE_SEGUNDOS = 24 * 3600

_ID = re.compile(r"^[0-9a-f]{32}$")
_NOME_NO_JOB = "capa_enviada.png"


class CapaInvalida(ValueError):
    """A imagem não serve; a mensagem vai direto para a tela."""


def _pasta_de_envios(user_id: str) -> Path:
    return Path(settings.storage_dir) / "uploads" / "covers" / user_id


def salvar_envio(user_id: str, dados: bytes) -> dict:
    """Valida, recorta para 1080 × 800 e guarda. Devolve o id e as medidas originais."""
    if len(dados) > MAX_BYTES:
        raise CapaInvalida("Imagem muito grande (máx. 10 MB).")
    try:
        Image.open(io.BytesIO(dados)).verify()
        img = Image.open(io.BytesIO(dados))
        # Foto de celular vem deitada com a rotação só nos metadados.
        img = ImageOps.exif_transpose(img).convert("RGB")
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError):
        raise CapaInvalida("Arquivo inválido: envie uma imagem PNG, JPEG ou WebP.")

    largura, altura = img.size
    capa = ImageOps.fit(img, (COVER_W, COVER_H), Image.LANCZOS, centering=(0.5, 0.5))

    envio_id = uuid4_hex()
    pasta = _pasta_de_envios(user_id)
    pasta.mkdir(parents=True, exist_ok=True)
    capa.save(pasta / f"{envio_id}.png", format="PNG")
    logger.info(f"Capa enviada {envio_id}: {largura}x{altura} → {COVER_W}x{COVER_H}")
    return {"id": envio_id, "width": largura, "height": altura}


def mover_para_o_job(user_id: str, envio_id: str, job_id: str) -> str:
    """Leva o envio para a pasta do job e devolve o caminho. Um envio serve a um job só."""
    if not _ID.match(envio_id or ""):
        raise CapaInvalida("Capa inválida. Envie a imagem de novo.")
    origem = _pasta_de_envios(user_id) / f"{envio_id}.png"
    if not origem.exists():
        raise CapaInvalida("A capa enviada expirou. Envie a imagem de novo.")
    destino = settings.clips_dir / job_id / _NOME_NO_JOB
    destino.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(origem), destino)
    return str(destino)


def apagar_envios_vencidos() -> int:
    """Remove os envios que ninguém usou num job. Devolve quantos."""
    base = Path(settings.storage_dir) / "uploads" / "covers"
    if not base.exists():
        return 0
    limite = time.time() - VALIDADE_SEGUNDOS
    apagados = 0
    for arquivo in base.glob("*/*.png"):
        try:
            if arquivo.stat().st_mtime < limite:
                arquivo.unlink()
                apagados += 1
        except OSError:
            continue
    return apagados
