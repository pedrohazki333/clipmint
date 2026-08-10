"""
Registra qual processo está trabalhando em cada job.

O pipeline roda em dois lugares: dentro do servidor (BackgroundTasks) e num
processo separado (`python -m app.scripts.resume_job`, que sobrevive ao reload
do uvicorn). Por isso o startup do servidor não pode assumir que todo job "em
execução" é órfão — pode haver outro processo renderizando agora.

O lock é um arquivo com o PID de quem está trabalhando. Se o PID não existe
mais, o job é órfão de verdade e pode ser reconciliado. Lock de arquivo com PID
basta aqui: é uma ferramenta local, um usuário, sem concorrência entre máquinas.
"""

import logging
import os
from contextlib import contextmanager
from pathlib import Path

from app.config import settings

logger = logging.getLogger(__name__)


def _lock_path(job_id: str) -> Path:
    return settings.locks_dir / f"{job_id}.pid"


def _process_alive(pid: int) -> bool:
    """Sinal 0 não faz nada — só verifica se o processo existe."""
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True  # existe, só pertence a outro usuário
    return True


def owner_pid(job_id: str) -> int | None:
    """
    PID do processo que está trabalhando no job, ou None se ninguém está.

    Lock apontando para um processo morto conta como ninguém (lock obsoleto de
    um processo que caiu antes de liberar).
    """
    try:
        pid = int(_lock_path(job_id).read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        return None
    return pid if _process_alive(pid) else None


@contextmanager
def held(job_id: str):
    """Marca este processo como dono do job enquanto o bloco executa."""
    path = _lock_path(job_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(str(os.getpid()), encoding="utf-8")
    try:
        yield
    finally:
        try:
            path.unlink(missing_ok=True)
        except OSError as exc:  # não deixa a limpeza derrubar o pipeline
            logger.warning(f"[{job_id}] Falha ao liberar o lock: {exc}")
