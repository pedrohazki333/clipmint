"""
O que há dentro de um clipe que já viralizou, sem ter o vídeo de origem.

O pipeline de referência que já existia (services/aligner.py + workers/
reference_pipeline.py) aprende com o clipe de outro criador comparando-o com o
vídeo original: baixa o original, transcreve os dois e localiza onde o corte foi
feito. Isso responde a melhor pergunta possível — por que ESTE recorte, e não o
de dois minutos antes — mas cobra um preço que na prática impede o aprendizado:
é preciso saber e ter acesso ao vídeo de origem. Um clipe salvo do TikTok quase
nunca diz de onde saiu, e quando diz, o original pode ser uma live de seis horas
que não vale baixar.

Este módulo troca a pergunta. Sem o original não dá para saber o que ficou de
fora, então o objeto de estudo passa a ser o clipe em si: o que ele mostra, o
que ele toca e o que ele fala, segundo a segundo. É uma perícia, não um
alinhamento.

A evidência vem de quatro medições independentes, e a independência é o ponto:

  1. FALA    — transcrição word-level (AssemblyAI), com os instantes.
  2. SOM     — loudness momentânea (ebur128), a mesma medida de
               services/audio_events.py. Diz onde estão os picos, quanta energia
               tem o gancho e onde o clipe respira. Um clipe de gameplay em que
               a música entra no segundo 4 e o grito vem no 12 não se parece em
               nada, na curva, com um de podcast falado.
  3. IMAGEM  — quadros lidos pelo Opus 5: o que está na tela e, sobretudo, o
               texto queimado no vídeo. Esse texto costuma ser o gancho de
               verdade e não existe em nenhuma outra fonte.
  4. EDIÇÃO  — os cortes de cena, via detector do FFmpeg. Ritmo de corte é uma
               das poucas coisas copiáveis direto, e é invisível na transcrição.

Nenhuma delas sozinha explica o clipe. A síntese (services/reference_analyzer.py,
analyze_standalone_clip) recebe as quatro alinhadas na mesma linha do tempo — é
aí que a leitura fica fina.

Custo: uma chamada de visão (~14 quadros, ~6k tokens) e uma de síntese. Ou seja,
centavos por referência, e sem download nem transcrição de um vídeo de uma hora.
"""

import asyncio
import base64
import json
import logging
import shutil
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from statistics import median
from typing import Optional

import anthropic

from app.config import settings
from app.prompts.clip_forensics import VISION_QUESTION, VISION_SYSTEM
from app.services.audio_events import loudness_timeline

logger = logging.getLogger(__name__)

# Mesma largura da visão do pipeline principal (services/vision.py): 768px cabe
# no limite de qualquer modelo e mantém legível o texto queimado no vídeo, que
# aqui é evidência central.
_FRAME_WIDTH = 768
# Um degrau melhor que a visão comum: legenda pequena com contorno não pode
# borrar, e o custo é o mesmo (o que pesa no token é a resolução, não o arquivo).
_JPEG_QUALITY = "3"

_EXTRACT_TIMEOUT = 60
_CUTS_TIMEOUT = 180

# Extrações simultâneas de quadro: processos curtos num arquivo pequeno. O teto
# existe só para um clipe longo não abrir 40 ffmpegs de uma vez.
_MAX_EXTRACT_CONCURRENCY = 6

# Abaixo disto o ebur128 reporta o piso de silêncio digital, não nível real.
_SILENCE_FLOOR = -70.0

# Amostras mínimas para uma mediana significar alguma coisa. O ebur128 entrega
# ~10 por segundo, então 20 é o equivalente a 2s de material.
_MIN_SAMPLES = 20

# Um respiro precisa durar isto para contar como pausa. Num clipe de 30s, um
# segundo mudo é uma eternidade — régua bem menor que a de audio_events.py, que
# trabalha em cima de vídeos de uma hora.
_MIN_PAUSE = 1.0

# Quanto abaixo do nível de fala o trecho precisa estar para ser pausa de verdade.
_PAUSE_MAX_DB = -6.0

# Distância mínima entre dois picos relatados. Dois picos a meio segundo um do
# outro são o mesmo acontecimento contado duas vezes.
_PEAK_SPACING = 2.0
_MAX_PEAKS = 3

# Quanto o pico precisa estar acima da fala para valer a pena relatar. Sem esta
# régua o código preenchia os três lugares mesmo num clipe plano, e o segundo e
# o terceiro "picos" saíam no nível da fala — mesma armadilha documentada em
# audio_events.py (_EVENT_MIN_DB): anotação que aparece em todo lugar não
# informa nada, e aqui ela chegaria à síntese com cara de acontecimento.
_PEAK_MIN_DB = 3.0


@dataclass
class Frame:
    """Um quadro do clipe e o instante em que ele aparece."""

    time: float
    jpeg: bytes


@dataclass
class FrameNote:
    """O que a visão relatou sobre um quadro."""

    time: float
    on_screen: str
    text_overlay: Optional[str] = None


@dataclass
class VisualReadout:
    """A leitura da imagem do clipe inteiro."""

    frames: list[FrameNote] = field(default_factory=list)
    video_format: str = ""       # "facecam sobre gameplay", "rosto falando"...
    caption_style: Optional[str] = None
    branding: Optional[str] = None

    def as_prompt(self) -> str:
        """A linha do tempo visual em texto, para entrar na síntese."""
        header: list[str] = []
        if self.video_format:
            header.append(f"Formato: {self.video_format}")
        if self.caption_style:
            header.append(f"Legenda/texto: {self.caption_style}")
        if self.branding:
            header.append(f"Marca: {self.branding}")

        timeline = []
        for note in self.frames:
            entry = f"[{note.time:.1f}s] {note.on_screen}"
            if note.text_overlay:
                entry += f' | texto na tela: "{note.text_overlay}"'
            timeline.append(entry)

        if not header and not timeline:
            return "(sem leitura de imagem)"
        return "\n".join(header + ([""] if header and timeline else []) + timeline)


@dataclass
class AudioProfile:
    """A curva de som do clipe, reduzida ao que muda uma decisão."""

    speech_level: Optional[float] = None      # LUFS medianos da fala
    hook_energy: Optional[float] = None       # dB do gancho vs. o resto do clipe
    peaks: list[tuple[float, float]] = field(default_factory=list)   # (instante, dB vs fala)
    pauses: list[tuple[float, float]] = field(default_factory=list)  # (início, fim)

    def as_prompt(self, hook_seconds: Optional[float] = None) -> str:
        if self.speech_level is None:
            return "(sem leitura de áudio)"

        hook_seconds = (
            hook_seconds if hook_seconds is not None else settings.forensics_hook_seconds
        )
        lines = [f"Nível de fala: {self.speech_level:.1f} LUFS"]
        if self.hook_energy is not None:
            direction = "acima" if self.hook_energy >= 0 else "abaixo"
            lines.append(
                f"Os primeiros {hook_seconds:.0f}s estão {abs(self.hook_energy):.1f} dB "
                f"{direction} do resto do clipe"
            )
        if self.peaks:
            picos = ", ".join(f"{t:.1f}s ({d:+.1f} dB vs fala)" for t, d in self.peaks)
            lines.append(f"Picos de som: {picos}")
        if self.pauses:
            pausas = ", ".join(f"{a:.1f}-{b:.1f}s" for a, b in self.pauses)
            lines.append(f"Silêncios: {pausas}")
        else:
            lines.append("Silêncios: nenhum acima de 1s — o clipe não respira")
        return "\n".join(lines)


@dataclass
class ClipEvidence:
    """Tudo que foi medido e visto no clipe, pronto para a síntese."""

    duration: float
    words: list[dict] = field(default_factory=list)
    cuts: list[float] = field(default_factory=list)
    audio: AudioProfile = field(default_factory=AudioProfile)
    visual: VisualReadout = field(default_factory=VisualReadout)

    def cut_rhythm(self) -> str:
        """O ritmo de edição em uma linha."""
        if not self.cuts:
            return "Nenhum corte de edição detectado — plano único do começo ao fim"
        every = self.duration / (len(self.cuts) + 1)
        marks = ", ".join(f"{t:.1f}s" for t in self.cuts[:20])
        overflow = "..." if len(self.cuts) > 20 else ""
        return (
            f"{len(self.cuts)} corte(s) em {self.duration:.0f}s "
            f"(um a cada ~{every:.1f}s): {marks}{overflow}"
        )


# ─── Fala ──────────────────────────────────────────────────────────────────────

def timed_transcript(words: list[dict], seconds_per_line: float = 3.0) -> str:
    """
    A transcrição em linhas curtas, cada uma com o instante em que começa.

    Texto corrido esconde o ritmo — e ritmo é metade do que se quer aprender de
    um clipe curto. Quebrar por TEMPO (e não por número de palavras) deixa
    visível onde a fala corre e onde ela para, que é exatamente o que a síntese
    precisa cruzar com a curva de som.
    """
    if not words:
        return "(sem fala transcrita)"

    lines: list[str] = []
    current: list[str] = []
    line_start = float(words[0].get("start", 0.0))

    for word in words:
        start = float(word.get("start", 0.0))
        if current and start - line_start >= seconds_per_line:
            lines.append(f"[{line_start:.1f}s] " + " ".join(current))
            current = []
            line_start = start
        current.append(str(word.get("text", "")))

    if current:
        lines.append(f"[{line_start:.1f}s] " + " ".join(current))
    return "\n".join(lines)


# ─── Som ───────────────────────────────────────────────────────────────────────

def _speech_level(timeline: list[tuple[float, float]], words: list[dict]) -> Optional[float]:
    """
    Loudness mediana enquanto alguém fala — a referência do clipe.

    Limiar fixo em LUFS não serviria: cada clipe tem sua própria mixagem, e o
    que interessa é o pico ser alto *para aquele clipe*.
    """
    spoken: list[float] = []
    index = 0
    for t, value in timeline:
        if value <= _SILENCE_FLOOR:
            continue
        while index < len(words) and float(words[index].get("end", 0)) < t:
            index += 1
        if index < len(words):
            word = words[index]
            if float(word.get("start", 0)) <= t <= float(word.get("end", 0)):
                spoken.append(value)

    if len(spoken) >= _MIN_SAMPLES:
        return median(spoken)

    # Clipe muito curto, música por cima da fala, ou transcrição sem duração
    # própria nas palavras: cai para a mediana do áudio audível. É uma
    # referência pior, mas sem ela o bloco de som inteiro some do prompt — e um
    # clipe sem leitura de áudio é justamente o que este módulo existe para
    # evitar.
    audible = [v for _, v in timeline if v > _SILENCE_FLOOR]
    return median(audible) if len(audible) >= _MIN_SAMPLES else None


def summarize_loudness(
    timeline: list[tuple[float, float]],
    words: list[dict],
    duration: float,
    hook_seconds: Optional[float] = None,
) -> AudioProfile:
    """
    Reduz a curva de loudness ao que importa: gancho, picos e respiros.

    Função pura — recebe a linha do tempo já medida e devolve o resumo, para o
    comportamento ser testável sem ffmpeg.
    """
    if not timeline:
        return AudioProfile()

    hook_seconds = (
        hook_seconds if hook_seconds is not None else settings.forensics_hook_seconds
    )
    speech = _speech_level(timeline, words)
    if speech is None:
        return AudioProfile()

    audible = [(t, v) for t, v in timeline if v > _SILENCE_FLOOR]
    profile = AudioProfile(speech_level=speech)

    # Gancho: os primeiros segundos contra o resto do clipe. É a medida de
    # "este clipe abre alto ou abre no vazio", que a transcrição não dá.
    hook_values = [v for t, v in audible if t <= hook_seconds]
    rest_values = [v for t, v in audible if t > hook_seconds]
    if hook_values and rest_values:
        profile.hook_energy = median(hook_values) - median(rest_values)

    # Picos: o máximo de cada segundo, do mais alto para o mais baixo, sem
    # relatar dois vizinhos.
    per_second: dict[int, float] = {}
    for t, v in audible:
        bucket = int(t)
        per_second[bucket] = max(per_second.get(bucket, v), v)

    picked: list[tuple[float, float]] = []
    for bucket, value in sorted(per_second.items(), key=lambda kv: (-kv[1], kv[0])):
        if any(abs(bucket - t) < _PEAK_SPACING for t, _ in picked):
            continue
        above = value - speech
        if above < _PEAK_MIN_DB:
            break  # a ordem é decrescente: daqui para baixo nada mais qualifica
        picked.append((float(bucket), above))
        if len(picked) >= _MAX_PEAKS:
            break
    profile.peaks = sorted(picked)

    # Pausas: trechos contínuos bem abaixo da fala.
    pauses: list[tuple[float, float]] = []
    start: Optional[float] = None
    previous = 0.0
    for t, v in timeline:
        quiet = v - speech <= _PAUSE_MAX_DB
        if quiet and start is None:
            start = t
        elif not quiet and start is not None:
            if previous - start >= _MIN_PAUSE:
                pauses.append((round(start, 1), round(previous, 1)))
            start = None
        previous = t
    if start is not None and duration - start >= _MIN_PAUSE:
        pauses.append((round(start, 1), round(duration, 1)))
    profile.pauses = pauses

    return profile


# ─── Imagem ────────────────────────────────────────────────────────────────────

def frame_times(
    duration: float,
    count: Optional[int] = None,
    hook_seconds: Optional[float] = None,
) -> list[float]:
    """
    Os instantes a amostrar: denso no gancho, uniforme no resto.

    Uma grade uniforme erra justamente onde o clipe é decidido. Num clipe de 40s
    com 14 quadros, o primeiro intervalo teria quase 3 segundos — e o overlay do
    gancho, que costuma sair da tela antes disso, não apareceria em quadro
    nenhum. Por isso os primeiros segundos ganham amostras próprias e a grade
    uniforme só começa depois deles.

    O último quadro fica um pouco antes do fim: pedir exatamente a duração
    devolve arquivo vazio em boa parte dos containers.
    """
    count = count if count is not None else settings.forensics_frame_count
    hook_seconds = (
        hook_seconds if hook_seconds is not None else settings.forensics_hook_seconds
    )

    if duration <= 0 or count <= 0:
        return []

    last = max(0.0, duration - 0.15)

    # Clipe mais curto que a própria janela de gancho: não há "resto" para
    # amostrar, então a grade uniforme cobre tudo.
    if duration <= hook_seconds or count == 1:
        if count == 1:
            return [0.0]
        step = last / (count - 1)
        return [round(i * step, 3) for i in range(count)]

    hook = [t for t in (0.0, 0.4, 0.9, 1.6, 2.4) if t < hook_seconds]
    hook = hook[:max(1, count // 3)]

    remaining = count - len(hook)
    span = last - hook_seconds
    if remaining <= 1 or span <= 0:
        return hook + [last]

    step = span / (remaining - 1)
    rest = [round(hook_seconds + i * step, 3) for i in range(remaining)]
    return hook + rest


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


async def extract_frames(video_path: str, times: list[float]) -> list[Frame]:
    """
    Um quadro por instante pedido.

    Uma chamada de ffmpeg por quadro, com o seek antes do `-i` (rápido, sem
    decodificar o que vem antes). Diferente de services/vision.py, aqui NÃO se
    usa `-skip_frame nokey`: o keyframe mais próximo pode estar segundos longe
    do instante pedido, e num clipe de 30 segundos essa é a diferença entre ver
    e não ver o gancho. O arquivo é pequeno e local, então o custo é trivial.

    Quadro que falha é descartado, não interrompe: catorze menos um ainda conta
    a história do clipe.
    """
    if not times:
        return []

    tmpdir = tempfile.mkdtemp(prefix="clipmint_forensics_")
    gate = asyncio.Semaphore(_MAX_EXTRACT_CONCURRENCY)

    async def one(index: int, t: float) -> Optional[Frame]:
        out = f"{tmpdir}/f_{index:03d}.jpg"
        async with gate:
            try:
                code, _, stderr = await _run([
                    "ffmpeg", "-y", "-v", "error",
                    "-ss", f"{t:.3f}", "-i", video_path,
                    "-frames:v", "1", "-vf", f"scale={_FRAME_WIDTH}:-2",
                    "-q:v", _JPEG_QUALITY, out,
                ], _EXTRACT_TIMEOUT)
            except (RuntimeError, OSError) as exc:
                logger.warning(f"Quadro em {t:.1f}s falhou: {exc}")
                return None
        if code != 0 or not Path(out).exists():
            logger.warning(
                f"Quadro em {t:.1f}s falhou: {stderr.decode(errors='replace')[-200:]}"
            )
            return None
        return Frame(time=t, jpeg=Path(out).read_bytes())

    try:
        results = await asyncio.gather(*(one(i, t) for i, t in enumerate(times)))
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)

    return [f for f in results if f is not None]


def parse_cut_times(output: str) -> list[float]:
    """Instantes dos cortes na saída do `metadata=print` do FFmpeg."""
    times: list[float] = []
    for line in output.splitlines():
        line = line.strip()
        if not line.startswith("frame:"):
            continue
        for part in line.split():
            if part.startswith("pts_time:"):
                try:
                    times.append(round(float(part.split(":", 1)[1]), 2))
                except ValueError:
                    pass
    return times


async def detect_cuts(video_path: str, threshold: Optional[float] = None) -> list[float]:
    """
    Onde a edição corta de um plano para outro.

    Falha silenciosa: o resto da perícia continua valendo sem isto.
    """
    threshold = (
        threshold if threshold is not None else settings.forensics_scene_threshold
    )
    try:
        _, stdout, stderr = await _run([
            "ffmpeg", "-v", "info", "-i", video_path,
            "-filter:v", f"select='gt(scene,{threshold})',metadata=print:file=-",
            "-an", "-f", "null", "-",
        ], _CUTS_TIMEOUT)
    except (RuntimeError, OSError) as exc:
        logger.warning(f"Detecção de cortes falhou: {exc}")
        return []

    # `file=-` do metadata e `-f null -` disputam a mesma saída, e qual das duas
    # recebe o quê varia com a versão do ffmpeg. Varrer as duas custa nada e
    # evita um "nenhum corte detectado" que seria mentira.
    combined = stdout.decode(errors="replace") + "\n" + stderr.decode(errors="replace")
    return parse_cut_times(combined)


def _content_blocks(frames: list[Frame]) -> list[dict]:
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
    blocks.append({"type": "text", "text": VISION_QUESTION})
    return blocks


def parse_json_response(raw: str) -> dict:
    """Extrai o JSON da resposta, tolerando cerca de código markdown."""
    raw = raw.strip()
    if raw.startswith("```"):
        lines = raw.split("\n")
        raw = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])
    return json.loads(raw)


def build_readout(data: dict, frames: list[Frame]) -> VisualReadout:
    """
    Monta a leitura visual a partir do JSON da visão.

    Os instantes vêm dos quadros que FORAM enviados, nunca do que o modelo
    respondeu: uma lista com um item a mais colocaria a observação de um quadro
    no tempo de outro e, daí em diante, a linha do tempo inteira estaria
    mentindo — com cara de fato, para um modelo que vai cruzá-la com o som.
    """
    notes: list[FrameNote] = []
    for index, item in enumerate(data.get("frames") or []):
        if index >= len(frames):
            break
        if not isinstance(item, dict):
            continue
        on_screen = str(item.get("on_screen") or "").strip()
        if not on_screen:
            continue
        overlay = item.get("text_overlay")
        notes.append(FrameNote(
            time=frames[index].time,
            on_screen=on_screen,
            text_overlay=str(overlay).strip() or None if overlay else None,
        ))

    def _text(key: str) -> Optional[str]:
        value = data.get(key)
        text = str(value).strip() if value else ""
        return text or None

    return VisualReadout(
        frames=notes,
        video_format=_text("format") or "",
        caption_style=_text("caption_style"),
        branding=_text("branding"),
    )


async def read_frames(reference_id: str, frames: list[Frame]) -> VisualReadout:
    """
    Pergunta ao modelo de visão o que há nos quadros — uma chamada só, todos juntos.

    Juntos, e não um por vez, porque metade do que se quer saber só existe na
    sequência: se o texto na tela mudou, se o plano cortou, se a legenda é a
    mesma do começo ao fim. Catorze quadros custam ~6k tokens, o que cabe folgado
    numa chamada.

    Nunca levanta: sem a leitura visual a perícia fica pior, mas a fala, o som e
    os cortes seguem valendo.
    """
    if not frames:
        return VisualReadout()

    client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)
    try:
        message = await client.messages.create(
            model=settings.claude_forensics_model,
            max_tokens=settings.claude_forensics_max_tokens,
            system=VISION_SYSTEM,
            messages=[{"role": "user", "content": _content_blocks(frames)}],
        )
        texts = [b.text for b in message.content if b.type == "text"]
        if not texts:
            logger.warning(
                f"[{reference_id}] Visão do clipe não devolveu texto "
                f"(stop={message.stop_reason})"
            )
            return VisualReadout()
        data = parse_json_response(texts[0])
    except (anthropic.APIError, json.JSONDecodeError, ValueError, KeyError) as exc:
        logger.warning(
            f"[{reference_id}] Visão do clipe falhou: {type(exc).__name__}: {exc}"
        )
        return VisualReadout()

    readout = build_readout(data, frames)
    logger.info(
        f"[{reference_id}] Visão leu {len(readout.frames)}/{len(frames)} quadro(s) "
        f"(formato: {readout.video_format or 'não identificado'})"
    )
    return readout


# ─── Orquestração ──────────────────────────────────────────────────────────────

async def gather_evidence(
    reference_id: str,
    clip_path: str,
    audio_path: str,
    words: list[dict],
    duration: float,
) -> ClipEvidence:
    """
    Reúne fala, som, imagem e cortes do clipe na mesma linha do tempo.

    As três medições de mídia são independentes e rodam juntas: nenhuma depende
    do resultado da outra, e em série o tempo seria a soma em vez do maior.
    """
    logger.info(f"[{reference_id}] Perícia do clipe iniciada ({duration:.1f}s)")

    async def _loudness() -> list[tuple[float, float]]:
        try:
            return await loudness_timeline(audio_path)
        except (RuntimeError, OSError, FileNotFoundError) as exc:
            logger.warning(f"[{reference_id}] Sem leitura de loudness: {exc}")
            return []

    frames, timeline, cuts = await asyncio.gather(
        extract_frames(clip_path, frame_times(duration)),
        _loudness(),
        detect_cuts(clip_path),
    )

    visual = await read_frames(reference_id, frames)
    audio = summarize_loudness(timeline, words, duration)

    logger.info(
        f"[{reference_id}] Perícia completa: {len(frames)} quadro(s), "
        f"{len(cuts)} corte(s), {len(words)} palavra(s)"
    )
    return ClipEvidence(
        duration=duration,
        words=words,
        cuts=cuts,
        audio=audio,
        visual=visual,
    )
