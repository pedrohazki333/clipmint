"""
A prévia animada de um clipe pronto.

O cartão do clipe mostrava um retângulo de texto: título, nota, cinco eixos e
duas frases. Nada ali diz se o corte pegou o momento certo — para saber, era
preciso baixar o MP4 e abrir num player. Três segundos em movimento respondem
antes de qualquer texto.

**Por que MP4 e não GIF.** O mesmo trecho de 3s em 270×480 sai com ~120 KB em
H.264 e ~2,5 MB em GIF, que ainda por cima é limitado a 256 cores — num clipe
de gameplay isso vira faixa de cor no céu e no degradê da capa. Com uma dúzia
de cartões na tela a diferença é entre 1,5 MB e 30 MB de download. O `<video
muted loop playsinline>` do navegador toca em looping igual ao GIF e roda no
iOS sem sair para tela cheia.

**Por que o começo do clipe.** É onde está o gancho — é a parte pela qual o
clipe foi escolhido, e é o que decide se alguém para de rolar. Um trecho do
meio mostraria uma parte que a análise nunca julgou.

Sem áudio de propósito: a prévia toca sozinha quando entra na tela, e áudio
que começa sem ninguém pedir é a única coisa pior que nenhuma prévia.
"""

import asyncio
import logging
from pathlib import Path

from app.utils.ffmpeg import run_ffmpeg

logger = logging.getLogger(__name__)

#: Quanto do começo do clipe entra na prévia.
PREVIEW_SECONDS = 3.0
#: Largura da prévia. O cartão mostra ~180px de largura em tela cheia e ~360
#: num celular retina; 270 cobre os dois sem virar um segundo download pesado.
PREVIEW_WIDTH = 270
#: Teto próprio, bem abaixo do teto global do FFmpeg: recortar 3 segundos de um
#: arquivo que já está pronto é trabalho de segundos. Se passar disso, algo está
#: errado e não vale segurar o pipeline — a prévia é acessório.
PREVIEW_TIMEOUT = 90


def preview_path(clip_path: str | Path) -> Path:
    """O caminho da prévia de um clipe, derivado do arquivo dele.

    Derivado, e não guardado no banco: a prévia é sempre o mesmo nome ao lado do
    MP4, então uma coluna a mais só criaria a chance de os dois discordarem.
    """
    caminho = Path(clip_path)
    return caminho.with_name(f"{caminho.stem}_preview.mp4")


async def generate_preview(clip_path: str | Path) -> Path | None:
    """
    Gera a prévia de um clipe já renderizado. `None` se não der.

    Nunca levanta: um clipe sem prévia é um cartão sem animação, e derrubar o
    job por causa disso trocaria o produto inteiro por um enfeite.
    """
    origem = Path(clip_path)
    if not origem.is_file():
        return None

    destino = preview_path(origem)
    try:
        await run_ffmpeg(
            "-loglevel", "error",
            # -ss antes do -i: o seek é no contêiner, não decodificando até lá.
            "-ss", "0",
            "-t", f"{PREVIEW_SECONDS}",
            "-i", str(origem),
            "-an",
            "-vf", f"scale={PREVIEW_WIDTH}:-2",
            "-c:v", "libx264",
            "-preset", "veryfast",
            "-crf", "30",
            # Sem isto o navegador precisa baixar o arquivo inteiro antes de
            # mostrar o primeiro quadro: o índice fica no fim do MP4.
            "-movflags", "+faststart",
            # Um GOP curto para o loop reiniciar sem engasgo.
            "-g", "30",
            "-pix_fmt", "yuv420p",
            str(destino),
            description=f"prévia de {origem.name}",
            timeout=PREVIEW_TIMEOUT,
        )
    except Exception as e:  # noqa: BLE001 — acessório, nunca derruba o job
        logger.warning(f"Prévia de {origem.name} não foi gerada: {e}")
        destino.unlink(missing_ok=True)
        return None

    return destino if destino.is_file() else None


def remove_preview(clip_path: str | Path | None) -> None:
    """Apaga a prévia junto com o clipe (retenção, exclusão de job)."""
    if not clip_path:
        return
    preview_path(clip_path).unlink(missing_ok=True)
