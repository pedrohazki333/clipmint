"""
Um FFmpeg travado tem que virar erro, não job travado.

Sem teto de tempo o `communicate()` espera para sempre: o job fica preso em
"clipping", o DELETE não interrompe o pipeline e o retry recusa enquanto o lock
estiver vivo — sobrava reiniciar o servidor. Estes testes cobrem o teto e, mais
importante, que o processo seja mesmo MORTO: um FFmpeg que sobrevive ao timeout
continua gravando por cima do arquivo de saída.
"""

import asyncio
import os
import time

import pytest

from app.utils.ffmpeg import FFmpegTimeout, _run_with_timeout


def _alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    return True


def _run_capturando_pid(cmd: list[str], timeout: int) -> list[int]:
    """Roda esperando o timeout e devolve os PIDs criados, para conferir a morte."""
    pids: list[int] = []

    async def run():
        real = asyncio.create_subprocess_exec

        async def spy(*args, **kwargs):
            proc = await real(*args, **kwargs)
            pids.append(proc.pid)
            return proc

        asyncio.create_subprocess_exec = spy
        try:
            with pytest.raises(FFmpegTimeout):
                await _run_with_timeout(cmd, timeout=timeout, description="")
        finally:
            asyncio.create_subprocess_exec = real

    asyncio.run(run())
    return pids


def test_processo_lento_estoura_o_teto():
    async def run():
        with pytest.raises(FFmpegTimeout) as exc:
            await _run_with_timeout(["sleep", "30"], timeout=1, description="teste")
        return str(exc.value)

    mensagem = asyncio.run(run())
    assert "passou de 1s" in mensagem
    assert "teste" in mensagem


def test_processo_estourado_e_realmente_morto():
    """O erro não basta: o processo não pode continuar rodando por trás."""
    pids = _run_capturando_pid(["sleep", "30"], timeout=1)
    assert len(pids) == 1
    assert not _alive(pids[0]), "o processo sobreviveu ao timeout"


def test_processo_que_ignora_sigterm_ainda_e_morto():
    """
    SIGTERM não move processo preso em syscall — por isso existe o SIGKILL.

    O shell abaixo ignora o TERM de propósito: é o comportamento que faz um
    `terminate()` sozinho deixar o processo vivo para sempre.
    """
    pids = _run_capturando_pid(["sh", "-c", "trap '' TERM; sleep 30"], timeout=1)
    assert not _alive(pids[0]), "o processo ignorou o TERM e não levou KILL"


def test_processo_rapido_passa_normalmente():
    async def run():
        return await _run_with_timeout(
            ["sh", "-c", "echo ok"], timeout=30, description=""
        )

    returncode, stdout, _ = asyncio.run(run())
    assert returncode == 0
    assert stdout.strip() == b"ok"


def test_filho_do_processo_tambem_morre(tmp_path):
    """
    O sinal vai para o grupo, não só para o líder.

    Matando só o líder, o filho continuava vivo segurando o pipe e o `wait()`
    ficava preso esperando um EOF que não vinha: o abort levava os 30s do filho
    em vez dos 5s da carência. Este teste guarda o PID do filho num arquivo e
    confere que ele foi junto — e o tempo total confirma que não houve espera.
    """
    pid_file = tmp_path / "filho.pid"
    inicio = time.monotonic()
    _run_capturando_pid(
        ["sh", "-c", f"trap '' TERM; sleep 30 & echo $! > {pid_file}; wait"],
        timeout=1,
    )
    decorrido = time.monotonic() - inicio

    filho = int(pid_file.read_text().strip())
    assert not _alive(filho), "o filho sobreviveu — o sinal não alcançou o grupo"
    # 1s de teto + 5s de carência, com folga. Perto de 30s significaria que
    # ficamos presos esperando o filho terminar sozinho.
    assert decorrido < 12, f"o abort demorou {decorrido:.1f}s — ficou preso no pipe"
