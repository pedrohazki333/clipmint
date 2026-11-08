"""
A máquina não pode ficar sem memória por causa de um render.

Num teste real, com a máquina no limite, os processos filhos morreram com a mensagem
vazia e os 7 clipes de um job caíram em menos de 3 segundos, sem dizer por quê.
"""

import asyncio
import subprocess
import sys
from unittest.mock import AsyncMock, patch

import pytest

from app.config import settings
from app.errors import user_message
from app.services import memory_guard
from app.services.memory_guard import NotEnoughMemory, available_mb, render_slot, wait_for_memory
from app.services.segments import _single_decoder_graph, compact_segments, total_duration
from app.utils.processes import process_alive


# ─── A medição ─────────────────────────────────────────────────────────────────

def test_mede_a_memoria_desta_maquina():
    available = available_mb()
    assert available is not None and available > 0


# ─── Esperar por memória ───────────────────────────────────────────────────────

def _rapido(monkeypatch, espera=0):
    monkeypatch.setattr(settings, "render_min_available_mb", 1000)
    monkeypatch.setattr(settings, "render_memory_wait_seconds", espera)
    monkeypatch.setattr(settings, "render_memory_poll_seconds", 0)


def test_com_memoria_segue_direto(monkeypatch):
    _rapido(monkeypatch)
    monkeypatch.setattr(memory_guard, "available_mb", lambda: 5000)
    asyncio.run(wait_for_memory("j", "c"))


def test_espera_a_memoria_voltar(monkeypatch):
    _rapido(monkeypatch, espera=30)
    leituras = iter([100, 200, 1500])
    monkeypatch.setattr(memory_guard, "available_mb", lambda: next(leituras))
    asyncio.run(wait_for_memory("j", "c"))
    assert next(leituras, "fim") == "fim", "seguiu antes de a memória voltar"


def test_sem_memoria_falha_dizendo_o_motivo(monkeypatch):
    _rapido(monkeypatch)
    monkeypatch.setattr(memory_guard, "available_mb", lambda: 100)
    with pytest.raises(NotEnoughMemory, match="100 MB disponíveis"):
        asyncio.run(wait_for_memory("j", "c"))


def test_erro_de_memoria_chega_legivel_a_quem_usa():
    mensagem = user_message(NotEnoughMemory("Memória insuficiente para renderizar: 100 MB"))
    assert "Faltou memória" in mensagem
    assert "Retomar" in mensagem


def test_erro_de_memoria_chega_legivel_pelo_erro_do_job():
    """O job embrulha o erro do primeiro clipe nesta frase."""
    erro = RuntimeError(
        "Nenhum clip pôde ser renderizado (7 falha(s)). Primeiro erro: "
        "Memória insuficiente para renderizar: 100 MB disponíveis"
    )
    assert "Faltou memória" in user_message(erro)


def test_sem_leitura_de_memoria_nao_trava_o_render(monkeypatch):
    _rapido(monkeypatch)
    monkeypatch.setattr(memory_guard, "available_mb", lambda: None)
    asyncio.run(wait_for_memory("j", "c"))


def test_zero_desliga_a_guarda(monkeypatch):
    monkeypatch.setattr(settings, "render_min_available_mb", 0)
    monkeypatch.setattr(memory_guard, "available_mb", lambda: 1)
    asyncio.run(wait_for_memory("j", "c"))


# ─── Threads conforme a memória ────────────────────────────────────────────────

def test_com_folga_o_encoder_usa_todos_os_nucleos(monkeypatch):
    monkeypatch.setattr(settings, "render_fast_available_mb", 1600)
    monkeypatch.setattr(memory_guard, "available_mb", lambda: 2000)
    assert memory_guard.encoder_thread_args() == []


def test_apertado_o_encoder_limita_as_threads(monkeypatch):
    monkeypatch.setattr(settings, "render_fast_available_mb", 1600)
    monkeypatch.setattr(settings, "render_low_memory_threads", 4)
    monkeypatch.setattr(memory_guard, "available_mb", lambda: 1000)
    assert memory_guard.encoder_thread_args() == ["-threads", "4"]


def test_sem_leitura_o_encoder_nao_muda(monkeypatch):
    monkeypatch.setattr(memory_guard, "available_mb", lambda: None)
    assert memory_guard.encoder_thread_args() == []


# ─── Um render por vez ─────────────────────────────────────────────────────────

def test_renders_entram_um_de_cada_vez(monkeypatch):
    monkeypatch.setattr(settings, "render_concurrency", 1)
    monkeypatch.setattr(settings, "render_min_available_mb", 0)
    ativos = []
    pico = []

    async def render(nome):
        async with render_slot("j", nome):
            ativos.append(nome)
            pico.append(len(ativos))
            await asyncio.sleep(0.01)
            ativos.remove(nome)

    async def tudo():
        await asyncio.gather(*(render(str(i)) for i in range(4)))

    asyncio.run(tudo())
    assert max(pico) == 1


def test_clipe_que_falha_na_memoria_libera_a_vez(monkeypatch):
    _rapido(monkeypatch)
    monkeypatch.setattr(settings, "render_concurrency", 1)
    leituras = iter([100, 5000])
    monkeypatch.setattr(memory_guard, "available_mb", lambda: next(leituras))

    async def tudo():
        with pytest.raises(NotEnoughMemory):
            async with render_slot("j", "1"):
                pass
        async with render_slot("j", "2"):
            return "entrou"

    assert asyncio.run(asyncio.wait_for(tudo(), 5)) == "entrou"


# ─── Costura com um decodificador só ───────────────────────────────────────────

def test_trechos_proximos_usam_uma_entrada_so():
    first, span, graph = _single_decoder_graph([(100.0, 105.0), (105.5, 110.0)])
    assert first == 100.0
    assert span == pytest.approx(10.0)
    assert "between(t,0.000,5.000)+between(t,5.500,10.000)" in graph
    assert "[0:a]aselect" in graph


def test_trechos_distantes_ficam_em_entradas_separadas():
    """Um compilado decodificaria o vídeo inteiro para descartar quase tudo."""
    assert _single_decoder_graph([(100.0, 105.0), (3000.0, 3010.0)]) is None


def test_ordem_nao_cronologica_fica_em_entradas_separadas():
    """A ordem editorial do compilado é a montagem, e o filtro não volta no tempo."""
    assert _single_decoder_graph([(200.0, 205.0), (100.0, 105.0)]) is None


def test_um_trecho_so_nao_precisa_do_filtro():
    assert _single_decoder_graph([(100.0, 105.0)]) is None


def test_compact_passa_uma_entrada_so(tmp_path):
    chamada = AsyncMock()

    async def rodar():
        with (
            patch("app.services.segments.run_ffmpeg", chamada),
            patch("app.services.segments.get_duration", AsyncMock(return_value=9.5)),
        ):
            await compact_segments("j", "c", "v.mp4", [(100.0, 105.0), (105.5, 110.0)], str(tmp_path / "s.mp4"))

    asyncio.run(rodar())
    assert chamada.await_args.args.count("-i") == 1


def test_costura_real_sai_com_a_duracao_dos_trechos(tmp_path):
    """Com o ffmpeg de verdade, áudio e vídeo: o `select` não pode perder nem sobrar."""
    fonte = tmp_path / "fonte.mp4"
    subprocess.run(
        ["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", "testsrc=size=160x90:rate=30:duration=20",
         "-f", "lavfi", "-i", "sine=frequency=440:duration=20", "-shortest",
         "-c:v", "libx264", "-preset", "ultrafast", "-c:a", "aac", str(fonte)],
        check=True, timeout=60,
    )
    trechos = [(2.0, 6.0), (7.0, 12.0), (15.0, 18.0)]
    saida = tmp_path / "costura.mp4"
    total = asyncio.run(compact_segments("j", "c", str(fonte), trechos, str(saida)))

    assert saida.exists()
    assert total == pytest.approx(total_duration(trechos), abs=0.1)


# ─── Perguntar se o processo existe não pode matá-lo ───────────────────────────

def _dorminhoco():
    return subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])


def test_perguntar_nao_mata_o_processo():
    """No Windows, `os.kill(pid, 0)` matava quem era verificado, sem erro nenhum."""
    proc = _dorminhoco()
    try:
        assert process_alive(proc.pid) is True
        assert process_alive(proc.pid) is True
        assert proc.poll() is None, "a verificação matou o processo"
    finally:
        proc.kill()
        proc.wait()


def test_processo_morto_nao_conta_como_vivo():
    proc = subprocess.Popen([sys.executable, "-c", "pass"])
    proc.wait()
    assert process_alive(proc.pid) is False


def test_pid_invalido_nao_conta_como_vivo():
    assert process_alive(0) is False
    assert process_alive(-1) is False
