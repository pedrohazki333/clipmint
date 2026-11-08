"""
Perguntas sobre processos que têm respostas diferentes em cada sistema.

Existe por causa de um engano caro: no Windows, `os.kill(pid, 0)` não pergunta se o
processo existe. O `0` é tratado como pedido de término, e o processo verificado
morre, sem exceção e com exit 0. Foi assim que um reprocessamento sumiu sem deixar
erro: o backend subiu ao mesmo tempo, conferiu o lock do job e matou quem o segurava.
"""

import os
import sys

_WINDOWS = sys.platform == "win32"

# Direito mínimo para perguntar o estado: abrir com ele não interfere no processo.
_PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
_ERROR_ACCESS_DENIED = 5
_STILL_ACTIVE = 259


def _alive_windows(pid: int) -> bool:
    import ctypes
    from ctypes import wintypes

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.OpenProcess.restype = wintypes.HANDLE
    kernel32.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
    kernel32.GetExitCodeProcess.argtypes = (wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD))
    kernel32.CloseHandle.argtypes = (wintypes.HANDLE,)

    handle = kernel32.OpenProcess(_PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not handle:
        # Sem permissão é porque ele existe e é de outro usuário.
        return ctypes.get_last_error() == _ERROR_ACCESS_DENIED
    try:
        code = wintypes.DWORD()
        if not kernel32.GetExitCodeProcess(handle, ctypes.byref(code)):
            return True  # não deu para saber: "vivo" é o lado seguro para um lock
        return code.value == _STILL_ACTIVE
    finally:
        kernel32.CloseHandle(handle)


def process_alive(pid: int) -> bool:
    """O processo existe? Só pergunta, sem efeito nenhum sobre ele."""
    if pid <= 0:
        return False
    if _WINDOWS:
        return _alive_windows(pid)
    try:
        os.kill(pid, 0)  # no POSIX o sinal 0 só verifica mesmo
    except ProcessLookupError:
        return False
    except PermissionError:
        return True  # existe, só pertence a outro usuário
    return True
