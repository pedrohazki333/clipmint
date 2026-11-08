"""
Um FFmpeg travado tem que virar erro, não job travado.

Sem teto de tempo o `communicate()` espera para sempre: o job fica preso em
"clipping", o DELETE não interrompe o pipeline e o retry recusa enquanto o lock
estiver vivo — sobrava reiniciar o servidor. Estes testes cobrem o teto e, mais
importante, que o processo seja mesmo MORTO: um FFmpeg que sobrevive ao timeout
continua gravando por cima do arquivo de saída.

Os processos de teste são Python, e não `sleep` e `sh`: precisam existir igual nos
dois sistemas em que isto roda, e o PID de um `sh` no Windows nem é o do sistema.
"""

import asyncio
import sys
import time

import pytest

from app.utils.ffmpeg import FFmpegTimeout, _run_with_timeout
from app.utils.processes import process_alive

_DORME = [sys.executable, "-c", "import time; time.sleep(30)"]
_IGNORA_TERM = [
    sys.executable,
    "-c",
    "import signal, time\n"
    "if hasattr(signal, 'SIGTERM'): signal.signal(signal.SIGTERM, signal.SIG_IGN)\n"
    "time.sleep(30)",
]


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
            await _run_with_timeout(_DORME, timeout=1, description="teste")
        return str(exc.value)

    mensagem = asyncio.run(run())
    assert "passou de 1s" in mensagem
    assert "teste" in mensagem


def test_processo_estourado_e_realmente_morto():
    """O erro não basta: o processo não pode continuar rodando por trás."""
    pids = _run_capturando_pid(_DORME, timeout=1)
    assert pids
    assert not process_alive(pids[0]), "o processo sobreviveu ao timeout"


def test_processo_que_ignora_sigterm_ainda_e_morto():
    """
    SIGTERM não move processo preso em syscall — por isso existe o SIGKILL.

    O processo abaixo ignora o TERM de propósito: é o comportamento que faz um
    `terminate()` sozinho deixar o processo vivo para sempre.
    """
    pids = _run_capturando_pid(_IGNORA_TERM, timeout=2)
    assert not process_alive(pids[0]), "o processo ignorou o TERM e não levou KILL"


def test_processo_rapido_passa_normalmente():
    async def run():
        return await _run_with_timeout(
            [sys.executable, "-c", "print('ok')"], timeout=30, description=""
        )

    returncode, stdout, _ = asyncio.run(run())
    assert returncode == 0
    assert stdout.strip() == b"ok"


def test_filho_do_processo_tambem_morre(tmp_path):
    """
    O sinal vai para a árvore, não só para o líder.

    Matando só o líder, o filho continuava vivo segurando o pipe e o `wait()`
    ficava preso esperando um EOF que não vinha: o abort levava os 30s do filho
    em vez dos 5s da carência. Este teste guarda o PID do filho num arquivo e
    confere que ele foi junto — e o tempo total confirma que não houve espera.
    """
    pid_file = tmp_path / "filho.pid"
    lider = (
        "import pathlib, signal, subprocess, sys, time\n"
        "if hasattr(signal, 'SIGTERM'): signal.signal(signal.SIGTERM, signal.SIG_IGN)\n"
        "f = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(30)'])\n"
        f"pathlib.Path({str(pid_file)!r}).write_text(str(f.pid))\n"
        "f.wait()"
    )
    inicio = time.monotonic()
    _run_capturando_pid([sys.executable, "-c", lider], timeout=2)
    decorrido = time.monotonic() - inicio

    filho = int(pid_file.read_text().strip())
    assert not process_alive(filho), "o filho sobreviveu — o sinal não alcançou a árvore"
    # 2s de teto + 5s de carência, com folga. Perto de 30s significaria que
    # ficamos presos esperando o filho terminar sozinho.
    assert decorrido < 14, f"o abort demorou {decorrido:.1f}s — ficou preso no pipe"
