"""
O que a câmera viu.

A análise de viralidade lê texto, e o áudio já diz onde o texto tem buracos
barulhentos (ver services/audio_events.py). Falta a terceira pergunta: o que
estava na tela.

Ela importa por um motivo concreto, medido no vídeo do Alan: no evento que
motivou este módulo — o personagem do Fall arremessado ao mar — a tela do
streamer não mostra nada de especial. Ele estava pescando do outro lado da
ilha; o que aconteceu, aconteceu fora do ponto de vista dele. O que a imagem
mostra é a FACECAM: o cara rindo alto. A reação é o sinal visual, não a cena.

Por isso as perguntas aqui são sempre duas e separadas — o que acontece na cena
e o que o rosto mostra —, e o prompt diz explicitamente que é normal a cena não
mudar. Um modelo pressionado a achar acontecimento na tela principal inventa um.

Custo: a extração usa SÓ keyframes. Medido num fonte AV1 4K60, uma janela de
40s custa 0,84s assim contra 18,4s decodificando tudo — 22x, e o mesmo tempo
para 7 ou 40 quadros, porque o gargalo é o decodificador, não a quantidade.
Errar essa escolha é o que transformaria este módulo em algo caro demais para
rodar em todo job.
"""

import asyncio
import base64
import json
import logging
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import anthropic

from app.config import settings

logger = logging.getLogger(__name__)


# Largura dos quadros enviados. 768px cabe folgado no limite de qualquer modelo
# atual e mantém legível o HUD do jogo e a expressão na facecam; medido em
# ~450 tokens por quadro, ~3.2k por janela de 7.
_FRAME_WIDTH = 768
_JPEG_QUALITY = "4"

# ffmpeg/ffprobe numa janela curta são rápidos, mas um arquivo problemático não
# pode pendurar o job.
_PROBE_TIMEOUT = 120
_EXTRACT_TIMEOUT = 300

# Chamadas simultâneas à API. O paralelismo existe para a latência não somar
# (10s por janela × N janelas seria pior que o render), mas sem teto vira
# rajada de 20 requisições e 429.
_MAX_CONCURRENCY = 4


@dataclass
class Keyframe:
    """Um quadro e o instante do vídeo em que ele aparece."""

    time: float
    jpeg: bytes


@dataclass
class Scene:
    """
    O que a visão relatou sobre uma janela do vídeo.

    Só descrição e limites. Não há aqui nenhum campo de julgamento — nem
    "vale a pena", nem "acontece algo": a primeira versão tinha um booleano
    desses e ele devolveu respostas opostas para a MESMA janela em duas
    execuções seguidas. Alerta que oscila entre rodadas idênticas treina quem
    o lê a ignorá-lo, então ele saiu. Descrição e instantes são estáveis; é o
    que este módulo entrega.
    """

    on_screen: str
    reaction: Optional[str] = None
    event_start: Optional[float] = None
    event_end: Optional[float] = None

    def summary(self) -> str:
        """Uma linha para entrar na anotação da transcrição."""
        parts = [self.on_screen.strip()]
        if self.reaction:
            parts.append(f"Reação: {self.reaction.strip()}")
        return " ".join(p for p in parts if p)


# ─── Extração de quadros ───────────────────────────────────────────────────────

async def _run(cmd: list[str], timeout: int) -> tuple[int, bytes, bytes]:
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except asyncio.TimeoutError:
        proc.kill()
        raise RuntimeError(f"{cmd[0]} excedeu {timeout}s")
    return proc.returncode, stdout, stderr


async def keyframe_times(video_path: str, start: float, end: float) -> list[float]:
    """
    Instantes dos keyframes dentro da janela, na ordem.

    `-read_intervals` limita a leitura à janela em vez de varrer o arquivo
    inteiro: 0,8s contra dezenas de segundos num vídeo de uma hora.
    """
    code, stdout, stderr = await _run([
        "ffprobe", "-v", "error", "-skip_frame", "nokey",
        "-select_streams", "v:0", "-show_entries", "frame=pts_time",
        "-read_intervals", f"{max(0.0, start):.3f}%+{max(0.1, end - start):.3f}",
        "-of", "csv=p=0", video_path,
    ], _PROBE_TIMEOUT)

    if code != 0:
        raise RuntimeError(f"ffprobe falhou: {stderr.decode(errors='replace')[-300:]}")

    times: list[float] = []
    for line in stdout.decode(errors="replace").splitlines():
        line = line.strip().rstrip(",")
        if not line:
            continue
        try:
            times.append(float(line))
        except ValueError:
            continue
    return times


async def extract_keyframes(
    video_path: str, start: float, end: float, max_frames: int
) -> list[Keyframe]:
    """
    Os keyframes da janela, com o instante de cada um.

    Devolve lista vazia em qualquer falha: a visão é uma camada extra, e um
    vídeo que o ffmpeg não consegue ler deve continuar sendo analisado pelo
    texto e pelo áudio como antes.
    """
    start = max(0.0, start)
    if end <= start:
        return []

    try:
        times = await keyframe_times(video_path, start, end)
    except (RuntimeError, OSError) as exc:
        logger.warning(f"Sem keyframes em [{start:.1f}-{end:.1f}]: {exc}")
        return []

    if not times:
        return []

    tmpdir = tempfile.mkdtemp(prefix="clipmint_vis_")
    try:
        code, _, stderr = await _run([
            "ffmpeg", "-v", "error", "-skip_frame", "nokey",
            "-ss", f"{start:.3f}", "-t", f"{end - start:.3f}", "-i", video_path,
            "-vf", f"scale={_FRAME_WIDTH}:-1", "-vsync", "0",
            "-q:v", _JPEG_QUALITY, f"{tmpdir}/f_%04d.jpg",
        ], _EXTRACT_TIMEOUT)

        if code != 0:
            logger.warning(
                f"ffmpeg falhou em [{start:.1f}-{end:.1f}]: "
                f"{stderr.decode(errors='replace')[-300:]}"
            )
            return []

        files = sorted(Path(tmpdir).glob("f_*.jpg"))
        # ffprobe e ffmpeg podem discordar por um quadro nas bordas da janela;
        # o zip para no menor e ninguém fica com timestamp trocado.
        frames = [
            Keyframe(time=t, jpeg=p.read_bytes())
            for t, p in zip(times, files)
        ]
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)

    if len(frames) <= max_frames:
        return frames

    # Amostra uniforme preservando as pontas: o começo e o fim da janela são
    # justamente onde o limite do corte vai ser decidido.
    step = (len(frames) - 1) / (max_frames - 1)
    picked = [frames[round(i * step)] for i in range(max_frames)]
    return picked


# ─── Chamada de visão ──────────────────────────────────────────────────────────

_SYSTEM = """Você olha quadros de um vídeo e relata o que está na imagem. Você é um observador, não um crítico: descreva o que aconteceu, não se foi bom.

Os quadros vêm em ordem, cada um precedido do instante em que aparece no vídeo.

Relate DUAS coisas, separadamente:

1. `on_screen` — o que acontece na imagem principal (o jogo, a cena, o cenário).
2. `reaction` — se houver uma facecam (um retângulo menor sobreposto, com o rosto de uma pessoa), o que o rosto e o corpo dela mostram. Sem facecam visível, use null.

ATENÇÃO — o caso mais comum e o mais fácil de errar: com frequência NADA de especial acontece na tela principal. A pessoa está reagindo a algo que aconteceu fora do ponto de vista dela — com outro jogador, em outra parte do mapa. Nesses casos a reação no rosto é o único sinal visual, e a tela principal segue numa atividade rotineira.

Quando for esse o caso, diga isso com todas as letras em `on_screen` ("atividade rotineira, nada de notável muda") em vez de procurar um acontecimento que não está lá. Inventar um evento na cena é o pior erro possível aqui: a descrição chega adiante com cara de fato e contamina a decisão de corte.

Se os quadros forem escuros, ilegíveis ou ambíguos demais, diga isso."""

JSON_RULES = """
Responda SOMENTE com JSON válido, sem markdown e sem texto fora do JSON:

{
  "on_screen": "o que acontece na imagem principal, em uma ou duas frases",
  "reaction": "o que o rosto na facecam mostra, ou null se não houver facecam",
  "event_start": null,
  "event_end": null
}

- `event_start` / `event_end`: os instantes em que o acontecimento visual começa e termina — incluindo quando o acontecimento é a REAÇÃO no rosto e não a cena. Use SOMENTE valores da lista de instantes que você recebeu, ou null quando não der para determinar. Preferir null a chutar.
- Não julgue se o trecho é bom, interessante ou viral. Relate o que está na imagem."""


def _content_blocks(frames: list[Keyframe], question: str) -> list[dict]:
    blocks: list[dict] = []
    for frame in frames:
        blocks.append({"type": "text", "text": f"t = {frame.time:.1f}s"})
        blocks.append({
            "type": "image",
            "source": {
                "type": "base64",
                "media_type": "image/jpeg",
                "data": base64.standard_b64encode(frame.jpeg).decode(),
            },
        })
    blocks.append({"type": "text", "text": question})
    return blocks


def _parse(raw: str) -> dict:
    raw = raw.strip()
    if raw.startswith("```"):
        lines = raw.split("\n")
        raw = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])
    return json.loads(raw)


async def _ask(job_id: str, frames: list[Keyframe], question: str) -> Optional[Scene]:
    """
    Uma pergunta sobre uma janela. None em qualquer falha.

    Nunca levanta: a visão é camada extra, e um erro dela não pode derrubar um
    job que já pagou download, transcrição e análise.
    """
    if not frames:
        return None

    client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)
    try:
        message = await client.messages.create(
            model=settings.claude_vision_model,
            max_tokens=settings.claude_vision_max_tokens,
            system=_SYSTEM,
            messages=[{"role": "user", "content": _content_blocks(frames, question)}],
        )
        texts = [b.text for b in message.content if b.type == "text"]
        if not texts:
            logger.warning(f"[{job_id}] Visão não devolveu texto (stop={message.stop_reason})")
            return None
        data = _parse(texts[0])
    except (anthropic.APIError, json.JSONDecodeError, ValueError, KeyError) as exc:
        logger.warning(f"[{job_id}] Chamada de visão falhou: {type(exc).__name__}: {exc}")
        return None

    valid_times = {round(f.time, 1) for f in frames}

    def _time(key: str) -> Optional[float]:
        value = data.get(key)
        if value is None:
            return None
        try:
            value = float(value)
        except (TypeError, ValueError):
            return None
        # O prompt manda usar instantes da lista; um valor inventado fora da
        # janela moveria o corte para um lugar que ninguém olhou.
        if round(value, 1) not in valid_times:
            lo, hi = min(valid_times), max(valid_times)
            if not (lo <= value <= hi):
                return None
        return value

    on_screen = str(data.get("on_screen") or "").strip()
    if not on_screen:
        return None

    reaction = data.get("reaction")
    return Scene(
        on_screen=on_screen,
        reaction=str(reaction).strip() if reaction else None,
        event_start=_time("event_start"),
        event_end=_time("event_end"),
    )


async def look(
    job_id: str,
    video_path: str,
    start: float,
    end: float,
    question: str,
    max_frames: Optional[int] = None,
) -> Optional[Scene]:
    """Extrai os keyframes de uma janela e pergunta o que há neles."""
    frames = await extract_keyframes(
        video_path, start, end, max_frames or settings.vision_max_frames
    )
    if not frames:
        return None
    return await _ask(job_id, frames, question)


async def look_many(
    job_id: str,
    video_path: str,
    windows: list[tuple[float, float]],
    questions: list[str],
) -> list[Optional[Scene]]:
    """
    Olha várias janelas em paralelo, na ordem em que foram pedidas.

    Uma pergunta por janela: o refino de limites precisa dizer a cada chamada
    onde o corte está hoje, e isso muda de clipe para clipe.

    O teto de simultaneidade evita transformar um vídeo cheio de eventos numa
    rajada de requisições, e a latência deixa de somar — 20 janelas de ~10s
    viram ~50s em vez de 200s.
    """
    gate = asyncio.Semaphore(_MAX_CONCURRENCY)

    async def one(window: tuple[float, float], question: str) -> Optional[Scene]:
        async with gate:
            return await look(job_id, video_path, window[0], window[1], question)

    return list(await asyncio.gather(
        *(one(w, q) for w, q in zip(windows, questions))
    ))
