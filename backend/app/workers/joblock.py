"""
Registra qual processo está trabalhando em cada job.

O pipeline roda em dois lugares: dentro do servidor (BackgroundTasks) e num
processo separado (`python -m app.scripts.resume_job`, que sobrevive ao reload
do uvicorn). Por isso o startup do servidor não pode assumir que todo job "em
execução" é órfão — pode haver outro processo renderizando agora.

O lock é um arquivo com o PID de quem está trabalhando. Se o PID não existe
mais, o job é órfão de verdade e pode ser reconciliado. Lock de arquivo com PID
basta aqui: é uma ferramenta local, um usuário, sem concorrência entre máquinas.

O lock também é exclusivo: dois pipelines no mesmo job escrevem nos mesmos
arquivos (o vídeo mesclado, o áudio, os clips). Quando isso acontece a saída
sai corrompida sem nenhum erro aparente — o vídeo abre normalmente, mas com a
trilha de áudio remendada, o que desloca a transcrição e desalinha todos os
cortes. Por isso o segundo processo é recusado em vez de assumir o lock.
"""

import logging
import os
from contextlib import contextmanager
from pathlib import Path

from app.config import settings

logger = logging.getLogger(__name__)


class JobAlreadyRunning(RuntimeError):
    """Outro processo vivo já está trabalhando neste job."""

    def __init__(self, job_id: str, pid: int) -> None:
        super().__init__(f"Job {job_id} já está em processamento pelo PID {pid}")
        self.job_id = job_id
        self.pid = pid


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


def _create_exclusive(path: Path) -> int | None:
    """Cria o arquivo de lock, ou None se ele já existe (criação atômica)."""
    try:
        return os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
    except FileExistsError:
        return None


@contextmanager
def held(job_id: str):
    """
    Marca este processo como dono do job enquanto o bloco executa.

    Exclusivo: se outro processo vivo já é dono, levanta JobAlreadyRunning em
    vez de assumir o lock — quem chega depois desiste, quem já está trabalhando
    continua. Lock apontando para processo morto é obsoleto e pode ser tomado.
    """
    path = _lock_path(job_id)
    path.parent.mkdir(parents=True, exist_ok=True)

    fd = _create_exclusive(path)
    if fd is None:
        owner = owner_pid(job_id)
        if owner is not None:
            raise JobAlreadyRunning(job_id, owner)
        # Dono morreu sem liberar: o lock é lixo e pode ser substituído.
        path.unlink(missing_ok=True)
        fd = _create_exclusive(path)
        if fd is None:  # outro processo pegou o lock nesse meio-tempo
            raise JobAlreadyRunning(job_id, owner_pid(job_id) or 0)

    with os.fdopen(fd, "w") as handle:
        handle.write(str(os.getpid()))

    try:
        yield
    finally:
        try:
            # Só libera o que ainda é nosso: se o lock já foi substituído,
            # apagar aqui derrubaria a proteção do processo que o tomou.
            if owner_pid(job_id) == os.getpid():
                path.unlink(missing_ok=True)
        except OSError as exc:  # não deixa a limpeza derrubar o pipeline
            logger.warning(f"[{job_id}] Falha ao liberar o lock: {exc}")
