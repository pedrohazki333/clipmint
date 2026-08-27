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
from pathlib import Path

from app.config import settings

logger = logging.getLogger(__name__)


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
            opts["cookiefile"] = str(arquivo)
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
