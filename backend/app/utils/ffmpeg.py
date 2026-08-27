import asyncio
import json
import logging
import os
import signal
from pathlib import Path
from typing import Optional

from app.config import settings

logger = logging.getLogger(__name__)


class FFmpegTimeout(RuntimeError):
    """O processo passou do teto de tempo e foi abortado."""


async def _run_with_timeout(
    cmd: list[str], timeout: int, description: str
) -> tuple[int, bytes, bytes]:
    """
    Roda um processo externo com teto de tempo, matando-o se estourar.

    O teto é a diferença entre um job que falha e um job que trava. Sem ele o
    `communicate()` espera para sempre: o pipeline fica preso em "clipping", o
    DELETE não o interrompe e o retry recusa enquanto o lock estiver vivo — a
    única saída era reiniciar o servidor.

    Matar é em dois tempos porque SIGTERM não move um processo preso dentro de
    uma syscall (nem um que escolha ignorá-lo); depois de uma carência curta vem
    o SIGKILL, que o sistema operacional garante.

    E o sinal vai para o GRUPO de processos, não para o processo. Matar só o
    líder deixa os filhos dele vivos segurando as pontas dos pipes que estamos
    lendo — e aí o `wait()` fica preso esperando um EOF que não chega, que é o
    mesmo travamento que este teto existe para evitar. Medido: matando só o
    líder, abortar um processo com filho levava os 30s inteiros do filho em vez
    dos 5s da carência.
    """
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        # Grupo próprio, para o kill abaixo alcançar a árvore inteira.
        start_new_session=True,
    )
    try:
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except asyncio.TimeoutError:
        logger.error(
            f"{Path(cmd[0]).name} passou de {timeout}s e será abortado ({description})"
        )
        await _kill_tree(proc)
        raise FFmpegTimeout(
            f"{Path(cmd[0]).name} passou de {timeout}s e foi abortado"
            + (f" ({description})" if description else "")
        ) from None

    return proc.returncode, stdout, stderr


#: Carência entre o pedido educado (TERM) e o definitivo (KILL).
_KILL_GRACE = 5


async def _kill_tree(proc: asyncio.subprocess.Process) -> None:
    """Derruba o processo e tudo que ele tiver aberto, sem deixar sobra."""

    def sinalizar(sig: int) -> bool:
        """False = já não existe ninguém para receber."""
        try:
            os.killpg(os.getpgid(proc.pid), sig)
            return True
        except (ProcessLookupError, PermissionError):
            return False

    if not sinalizar(signal.SIGTERM):
        return
    try:
        await asyncio.wait_for(proc.wait(), timeout=_KILL_GRACE)
    except asyncio.TimeoutError:
        sinalizar(signal.SIGKILL)
        await proc.wait()


async def probe_video(video_path: str) -> dict:
    """
    Retorna metadados do vídeo via ffprobe (duração, dimensões, streams).
    """
    cmd = [
        "ffprobe", "-v", "quiet",
        "-print_format", "json",
        "-show_streams", "-show_format",
        video_path,
    ]
    returncode, stdout, stderr = await _run_with_timeout(
        cmd, settings.ffprobe_timeout, f"probe de {Path(video_path).name}"
    )
    if returncode != 0:
        raise RuntimeError(f"ffprobe failed: {stderr.decode(errors='replace')}")
    return json.loads(stdout.decode())


async def get_duration(media_path: str) -> float:
    """
    Duração real do arquivo em segundos, segundo o container.

    Levanta ValueError se o arquivo não declara duração — arquivo truncado no
    meio da escrita costuma ficar assim.
    """
    info = await probe_video(media_path)
    duration = info.get("format", {}).get("duration")
    if duration is None:
        raise ValueError(f"Arquivo sem duração declarada: {media_path}")
    return float(duration)


async def get_video_dimensions(video_path: str) -> tuple[int, int]:
    """Retorna (width, height) do vídeo."""
    info = await probe_video(video_path)
    for stream in info.get("streams", []):
        if stream.get("codec_type") == "video":
            return int(stream["width"]), int(stream["height"])
    raise ValueError(f"No video stream found in {video_path}")


async def run_ffmpeg(
    *args: str, description: str = "", timeout: Optional[int] = None
) -> None:
    """
    Executa um comando ffmpeg e levanta erro se falhar ou se travar.

    Args:
        *args: Argumentos do comando ffmpeg (sem o 'ffmpeg' inicial).
        description: Descrição para logging.
        timeout: Teto em segundos. Omitido, usa `settings.ffmpeg_timeout`.
    """
    cmd = ["ffmpeg", "-y", *args]
    if description:
        logger.info(f"FFmpeg: {description}")
    logger.debug(f"FFmpeg command: {' '.join(cmd)}")

    returncode, _stdout, stderr = await _run_with_timeout(
        cmd, timeout or settings.ffmpeg_timeout, description
    )

    if returncode != 0:
        error_output = stderr.decode(errors="replace")[-2000:]
        raise RuntimeError(f"FFmpeg failed ({description}): {error_output}")
