"""
As opções que TODA chamada ao yt-dlp precisa carregar.

Existe por um motivo concreto e caro: num servidor de datacenter o YouTube
responde *"Sign in to confirm you're not a bot"* para qualquer vídeo, inclusive
os públicos desde 2005. O bloqueio é por faixa de IP, não por vídeo — o mesmo
link que funciona numa conexão doméstica falha na VPS.

A saída é autenticar (cookies) ou sair por outro IP (proxy). Qualquer uma das
duas precisa chegar aos **dois** lugares que falam com o YouTube:

  - `services/quota.py` — a consulta de metadados, que decide se o job nasce;
  - `services/downloader.py` — o download de verdade.

Antes deste módulo cada um montava o próprio dicionário de opções. Configurar
só um seria pior que não configurar nenhum: a consulta passaria, o job nasceria,
o crédito seria reservado, e o download falharia minutos depois — cobrando ao
usuário a espera de um erro que já era conhecido no primeiro segundo.
"""

import logging
import os
import shutil
import tempfile
import time
from pathlib import Path

from app.config import settings

logger = logging.getLogger(__name__)

#: Prefixo das cópias descartáveis do arquivo de cookies.
_PREFIXO_COPIA = "clipmint-cookies-"
#: Cópia mais velha que isto é sobra de execução passada.
_VALIDADE_COPIA_S = 3600


def _limpar_copias_antigas() -> None:
    """Remove sobras de execuções anteriores. Falha em silêncio de propósito.

    Se a limpeza não der certo, o pior caso são alguns arquivos de 4 KB no
    diretório temporário — não é motivo para impedir um download.
    """
    limite = time.time() - _VALIDADE_COPIA_S
    try:
        for antiga in Path(tempfile.gettempdir()).glob(f"{_PREFIXO_COPIA}*"):
            try:
                if antiga.stat().st_mtime < limite:
                    antiga.unlink()
            except OSError:
                pass
    except OSError:
        pass


def _copia_descartavel(mestre: Path) -> str | None:
    """Uma cópia que o yt-dlp pode estragar à vontade.

    **Ele reescreve o arquivo de cookies.** Quando a sessão é rejeitada ou
    rotacionada pelo YouTube, ele salva por cima um jar SEM os cookies de
    autenticação — e a partir daí toda chamada vai sem credencial. Aconteceu em
    produção em 27/08/2026: o arquivo caiu de 2954 para 1843 bytes e perdeu
    `SID`, `HSID`, `SSID`, `APISID`, `SAPISID`, `LOGIN_INFO` e `__Secure-1PSID`
    numa única tentativa que deu errado.

    Entregando uma cópia, o que ele destrói é descartável e o mestre continua
    valendo. O que se perde é a renovação automática do cookie; o que se ganha é
    não perder a sessão inteira por causa de UMA chamada que falhou — e já se
    viu qual dos dois dói.

    Devolve `None` se não conseguir copiar. Nesse caso o yt-dlp vai sem cookies
    e a chamada falha com uma mensagem clara do YouTube, que é recuperável —
    entregar o mestre seria arriscar destruí-lo, que não é.
    """
    _limpar_copias_antigas()
    try:
        fd, destino = tempfile.mkstemp(prefix=_PREFIXO_COPIA, suffix=".txt")
        os.close(fd)
        shutil.copyfile(mestre, destino)
        os.chmod(destino, 0o600)
        return destino
    except OSError:
        logger.exception(
            "Não foi possível copiar %s. O yt-dlp vai seguir SEM cookies em vez "
            "de receber o arquivo original, que ele reescreveria.",
            mestre,
        )
        return None


def base_opts() -> dict:
    """Opções comuns a toda chamada do yt-dlp, montadas a partir do `.env`.

    Sem cookies nem proxy configurados devolve só o silêncio de sempre — que é
    o comportamento correto numa máquina doméstica, onde nada disso é preciso.
    """
    opts: dict = {"quiet": True, "no_warnings": True}

    caminho = (settings.ytdlp_cookies_file or "").strip()
    if caminho:
        arquivo = Path(caminho)
        if arquivo.is_file():
            copia = _copia_descartavel(arquivo)
            if copia:
                opts["cookiefile"] = copia
        else:
            # Falar alto aqui é o ponto. Um caminho errado faria o yt-dlp seguir
            # SEM cookies e voltar com "confirme que você não é um robô" — e
            # ninguém liga esse erro a um typo no .env.
            logger.error(
                "YTDLP_COOKIES_FILE aponta para %r, que não existe. O yt-dlp vai "
                "seguir sem autenticação e o YouTube provavelmente vai recusar.",
                caminho,
            )

    proxy = (settings.ytdlp_proxy or "").strip()
    if proxy:
        opts["proxy"] = proxy

    return opts


def descrever() -> str:
    """Como o yt-dlp está autenticado, para log e diagnóstico."""
    partes = []
    opts = base_opts()
    partes.append("cookies" if "cookiefile" in opts else "sem cookies")
    partes.append(f"proxy {opts['proxy']}" if "proxy" in opts else "sem proxy")
    return ", ".join(partes)
