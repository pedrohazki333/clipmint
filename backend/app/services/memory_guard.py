"""
Render só começa quando a máquina aguenta.

Costura e render são a parte cara em memória do pipeline, e a falta dela não vira um
erro legível: num teste real, com a máquina no limite, os processos filhos morreram
com a mensagem vazia e os 7 clipes do job caíram em menos de 3 segundos. O sistema
também roda na máquina pessoal do dono, onde a memória é dividida com o resto do que
ele está usando, e lá derrubar os outros programas é tão ruim quanto falhar.

Por isso duas regras, nesta ordem:

  - Um render por vez no processo, mesmo com dois jobs em paralelo. Eles esperam na
    fila em vez de competir pela mesma memória.
  - Antes de começar, confere a memória DISPONÍVEL e espera ela voltar. Passado o
    teto de espera, o clipe falha dizendo o motivo, e não some com erro vazio.

Disponível, e não livre: a memória de cache do sistema conta, porque ele a devolve
assim que alguém pede. Sem conseguir ler o valor, o render segue, porque travar todo
job por uma leitura que não existe nesse sistema seria pior que o risco.
"""

import asyncio
import logging
import sys
import time
from contextlib import asynccontextmanager
from typing import Optional

from app.config import settings

logger = logging.getLogger(__name__)


class NotEnoughMemory(RuntimeError):
    """A memória não voltou dentro do teto de espera."""


def _available_windows() -> Optional[int]:
    import ctypes

    class MemoryStatus(ctypes.Structure):
        _fields_ = [
            ("dwLength", ctypes.c_ulong),
            ("dwMemoryLoad", ctypes.c_ulong),
            ("ullTotalPhys", ctypes.c_ulonglong),
            ("ullAvailPhys", ctypes.c_ulonglong),
            ("ullTotalPageFile", ctypes.c_ulonglong),
            ("ullAvailPageFile", ctypes.c_ulonglong),
            ("ullTotalVirtual", ctypes.c_ulonglong),
            ("ullAvailVirtual", ctypes.c_ulonglong),
            ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
        ]

    status = MemoryStatus()
    status.dwLength = ctypes.sizeof(MemoryStatus)
    if not ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
        return None
    return int(status.ullAvailPhys / (1024 * 1024))


def _available_linux() -> Optional[int]:
    try:
        with open("/proc/meminfo", encoding="ascii") as source:
            for line in source:
                if line.startswith("MemAvailable:"):
                    return int(line.split()[1]) // 1024
    except (OSError, ValueError, IndexError):
        return None
    return None


def available_mb() -> Optional[int]:
    """Memória disponível em MB, ou None se este sistema não disser."""
    if sys.platform == "win32":
        return _available_windows()
    return _available_linux()


def encoder_thread_args() -> list[str]:
    """
    Quantas threads o x264 usa, conforme a memória de agora.

    Medido num clipe de 1080x1920 em 12 núcleos: 996 MB em 16,6s com todos, 716 MB
    em 39,3s com 4, e 673 MB em 53,8s com 2. O arquivo sai igual. Por isso: com folga,
    o render rápido; apertado, troca tempo por memória. Abaixo de 4 quase não economiza.
    """
    available = available_mb()
    if available is None or available >= settings.render_fast_available_mb:
        return []
    return ["-threads", str(settings.render_low_memory_threads)]


_slot: Optional[asyncio.Semaphore] = None
_slot_loop: Optional[asyncio.AbstractEventLoop] = None


def _render_slot() -> asyncio.Semaphore:
    """Um semáforo por event loop: criar no import o prenderia ao loop errado."""
    global _slot, _slot_loop
    loop = asyncio.get_running_loop()
    if _slot is None or _slot_loop is not loop:
        _slot = asyncio.Semaphore(max(1, settings.render_concurrency))
        _slot_loop = loop
    return _slot


async def wait_for_memory(job_id: str, clip_id: str) -> None:
    """Espera ter memória para um render. Levanta NotEnoughMemory no teto de espera."""
    needed = settings.render_min_available_mb
    if needed <= 0:
        return

    deadline = time.monotonic() + settings.render_memory_wait_seconds
    warned = False
    while True:
        available = available_mb()
        if available is None or available >= needed:
            if warned:
                logger.info(f"[{job_id}] Clip {clip_id}: memória voltou ({available} MB)")
            return
        if not warned:
            logger.warning(
                f"[{job_id}] Clip {clip_id}: {available} MB disponíveis, o render pede "
                f"{needed} MB — aguardando até {settings.render_memory_wait_seconds}s"
            )
            warned = True
        if time.monotonic() >= deadline:
            raise NotEnoughMemory(
                f"Memória insuficiente para renderizar: {available} MB disponíveis, "
                f"o render precisa de {needed} MB"
            )
        await asyncio.sleep(settings.render_memory_poll_seconds)


@asynccontextmanager
async def render_slot(job_id: str, clip_id: str):
    """Vez de renderizar: a fila primeiro, a memória depois, porque quem estava na
    frente pode ter acabado de devolver o que este precisa."""
    async with _render_slot():
        await wait_for_memory(job_id, clip_id)
        yield
