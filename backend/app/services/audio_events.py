"""
O que acontece nos buracos da transcrição.

A análise de viralidade lê só texto, e texto não distingue os dois tipos de
silêncio que existem num vídeo. Um é tempo morto: o cara pensando, caminhando,
lendo o chat. O outro é o momento mais alto do vídeo inteiro — a gargalhada, o
grito, a explosão, a jogada acontecendo — que a transcrição registra como
exatamente a mesma coisa: nada.

Foi assim que se perdeu o melhor corte de um vídeo de 56 minutos. Entre 50:30 e
50:51 não há uma palavra transcrita: são 21 segundos em que o personagem de um
dos jogadores é arremessado no mar e todo mundo cai na gargalhada. O prompt
manda penalizar silêncio longo, então o modelo fez o que foi mandado — começou
o clipe em 50:51, na primeira palavra depois do buraco, pegando só o comentário
sobre o que tinha acabado de acontecer. O fato ficou de fora do corte.

O áudio desfaz a ambiguidade sem precisar de modelo nenhum: naquele buraco a
loudness mediana era -24.9 LUFS contra -36.4 da fala em volta, com pico em
-12.3. O "silêncio" era o trecho mais alto da vizinhança.

Este módulo mede isso — uma passada de ebur128 sobre o áudio que já está em
disco — e classifica cada buraco como evento sonoro ou tempo morto. O resultado
tem dois usos: anotar a transcrição enviada ao Claude (para ele parar de ler
buraco alto como enchimento) e resgatar em Python o corte que começa logo
depois de um evento, que é o erro que se quer nunca mais cometer.
"""

import asyncio
import logging
import re
import wave
from dataclasses import dataclass
from statistics import median
from typing import Optional

import numpy as np

logger = logging.getLogger(__name__)

# Buraco menor que isto é respiração entre frases, não momento — e o
# universal-3-pro deixa muita palavra sem duração própria, o que cria buraquinho
# artificial na linha do tempo.
_MIN_GAP = 3.0

# Abaixo disto o ebur128 está reportando o piso de silêncio digital, não um
# nível de áudio real; entra na conta do buraco, mas não na referência de fala.
_SILENCE_FLOOR = -70.0

# Quanto o buraco precisa estar ACIMA do nível de fala para contar como evento.
# A distribuição medida num vídeo real é um contínuo, não dois grupos: com
# margem zero, 55% dos buracos viravam "evento" — nível de fala é fácil de
# alcançar com ruído de sala ou música de fundo, e anotação que aparece em todo
# lugar não informa nada. Acima de +3 dB sobra o que de fato soa alto.
_EVENT_MIN_DB = 3.0

# Para o resgate automático a régua é mais dura: aqui o Python mexe no corte
# sem ninguém julgando, e o prompt já cobre os casos limítrofes. O evento que
# motivou tudo isto (a gargalhada de 21s) mede +13.5 dB, com folga enorme.
_STRONG_EVENT_MIN_DB = 6.0
_STRONG_EVENT_MIN_DURATION = 4.0

# Abaixo disto o buraco é tempo morto de verdade. Entre este valor e o de
# evento fica a faixa ambígua — som ambiente, risada distante, fala de fundo —,
# que é reportada com a medição e sem rótulo: chamar de "tempo morto" um buraco
# a 2 dB da fala seria repetir o erro que este módulo existe para corrigir.
_DEAD_MAX_DB = -6.0

# A partir de quanta fala contínua antes do momento a construção deixa de ser
# uma frase de preparação e passa a ser o clipe. Medido num vídeo do Bahiaqz: a
# maioria dos eventos tem 8-25s de construção; o que precisava de corte longo
# tinha 128s — a separação é larga, e 30s cai no vazio entre os dois grupos.
_LONG_BUILDUP = 30.0

# Uma reação some poucos segundos depois do fato; um corte que começa dentro
# desta janela após o fim do buraco está pegando a reação sem a causa.
_REACTION_TOLERANCE = 4.0


# O outro jeito de perder a preparação: em vez de começar depois do evento, o
# corte começa EM CIMA dele. O clipe abre no meio da gargalhada, sem a fala que
# monta a piada — visto na prática quando a anotação de imagem deixou o modelo
# confiante o bastante para abrir direto no barulho.
_ONSET_TOLERANCE = 2.0

# Quanto de fala anterior ao evento entra junto, para o clipe abrir com o
# contexto do que vai acontecer em vez de abrir no baque seco.
_PREROLL_MAX = 9.0

_FRAME_RE = re.compile(r"^frame:\d+\s+pts:\S+\s+pts_time:([\d.]+)")
_M_RE = re.compile(r"lavfi\.r128\.M=(-?[\d.]+)")

# 56 minutos de WAV levam dezenas de segundos; o teto existe só para um áudio
# problemático não pendurar o job para sempre.
_TIMEOUT = 900


@dataclass
class Gap:
    """Um trecho sem palavras transcritas, com o que o áudio diz sobre ele."""

    start: float
    end: float
    loudness: float       # p90 da loudness momentânea dentro do buraco (LUFS)
    speech_level: float   # loudness mediana da fala no vídeo (LUFS)
    # O que a imagem mostrou nesta janela, quando a visão rodou. O áudio diz
    # QUANDO algo aconteceu; isto diz O QUÊ (ver services/vision.py).
    scene: Optional[str] = None
    # Onde começa a fala contínua que desemboca neste momento — o fim do buraco
    # anterior. Diz o TAMANHO da construção, que é o que faltava para o modelo
    # distinguir um pico solto de um payoff que levou minutos sendo montado.
    buildup_start: Optional[float] = None

    @property
    def buildup(self) -> float:
        """Segundos de fala sem pausa até este momento."""
        if self.buildup_start is None:
            return 0.0
        return max(0.0, self.start - self.buildup_start)

    @property
    def has_long_buildup(self) -> bool:
        """A construção é longa o bastante para mudar onde o corte começa."""
        return self.buildup >= _LONG_BUILDUP

    @property
    def duration(self) -> float:
        return self.end - self.start

    @property
    def above_speech(self) -> float:
        """dB acima (positivo) ou abaixo (negativo) do nível normal de fala."""
        return self.loudness - self.speech_level

    @property
    def is_event(self) -> bool:
        """O buraco tem som alto: aconteceu alguma coisa ali."""
        return self.above_speech >= _EVENT_MIN_DB

    @property
    def is_dead(self) -> bool:
        """Silêncio de verdade: bem abaixo da fala, o buraco que derruba retenção."""
        return self.above_speech <= _DEAD_MAX_DB

    @property
    def is_strong_event(self) -> bool:
        """Barulhento e longo o bastante para o resgate automático agir sozinho."""
        return (
            self.above_speech >= _STRONG_EVENT_MIN_DB
            and self.duration >= _STRONG_EVENT_MIN_DURATION
        )


# ─── Medição ───────────────────────────────────────────────────────────────────

async def loudness_timeline(audio_path: str) -> list[tuple[float, float]]:
    """
    Loudness momentânea (janela de 400ms do ebur128) a cada ~100ms.

    O ebur128 é a medida certa aqui porque acompanha percepção: gargalhada e
    grito sobem nela do mesmo jeito que sobem para quem está assistindo, o que
    um pico de amostra bruta não garante.

    Pública porque services/clip_forensics.py mede a mesma coisa num clipe já
    pronto — com outra régua, mas a partir desta mesma curva.
    """
    proc = await asyncio.create_subprocess_exec(
        "ffmpeg", "-v", "error", "-i", audio_path,
        "-af", "ebur128=metadata=1,ametadata=print:key=lavfi.r128.M:file=-",
        "-f", "null", "-",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=_TIMEOUT)
    except asyncio.TimeoutError:
        proc.kill()
        raise RuntimeError(f"ebur128 excedeu {_TIMEOUT}s em {audio_path}")

    if proc.returncode != 0:
        raise RuntimeError(
            f"ebur128 falhou: {stderr.decode(errors='replace')[-500:]}"
        )

    timeline: list[tuple[float, float]] = []
    t: Optional[float] = None
    for line in stdout.decode(errors="replace").splitlines():
        frame = _FRAME_RE.match(line)
        if frame:
            t = float(frame.group(1))
            continue
        value = _M_RE.search(line)
        if value and t is not None:
            timeline.append((t, float(value.group(1))))
            t = None

    return timeline


# ─── Nível fino, para decidir ONDE cortar ──────────────────────────────────────
#
# A curva do ebur128 acima responde "aconteceu algo neste buraco de 3s?". Para
# saber onde uma frase termina ela é grossa demais: a janela de 400ms atravessa
# uma pausa de 0,5s inteira e mistura a fala das duas pontas.
#
# E o timestamp da palavra não substitui o áudio. Medido num vídeo real com o
# universal-3-pro: "mil seguidores do dia" ocupa 0,08s no timestamp enquanto o
# áudio segue falando por 2s, e `pé.` dura 1,34s com 1,15s de silêncio dentro.
# Um clipe cortado no fim de `foda.` pelo timestamp ainda saiu com a palavra pela
# metade. Quem diz onde a fala parou é o áudio.

_RMS_STEP = 0.05

# Blocos por leitura do WAV: lê em pedaços porque o áudio de um vídeo de 3h passa
# de 300 MB, e isto roda com outros jobs ao lado.
_RMS_BLOCKS_PER_READ = 1200

_RMS_FLOOR_DB = -120.0

# Palavra mais curta que isto tem timestamp espremido, não fala de verdade — e
# entraria na referência medindo o que quer que estivesse tocando ali.
_MIN_WORD_FOR_REFERENCE = 0.1


@dataclass
class AudioLevels:
    """RMS em blocos de 50ms do áudio inteiro, com o nível de fala do vídeo."""

    levels: np.ndarray
    speech_level: float
    step: float = _RMS_STEP

    def quiet_runs(
        self, start: float, end: float, below_speech_db: float, min_duration: float
    ) -> list[tuple[float, float]]:
        """
        Trechos de [start, end] pelo menos `below_speech_db` abaixo da fala.

        O limiar é relativo porque cada vídeo tem sua mixagem, pelo mesmo motivo
        do `_speech_level`: o que interessa é estar baixo *para aquele vídeo*.
        """
        first = max(0, int(start / self.step))
        last = min(len(self.levels), int(np.ceil(end / self.step)))
        if last <= first:
            return []

        quiet = self.levels[first:last] <= self.speech_level - below_speech_db
        # Pontas das sequências de True: onde a máscara muda de valor.
        edges = np.flatnonzero(np.diff(np.concatenate(([False], quiet, [False])).astype(int)))
        runs = []
        for run_start, run_end in zip(edges[::2], edges[1::2]):
            a = (first + int(run_start)) * self.step
            b = (first + int(run_end)) * self.step
            if b - a >= min_duration:
                runs.append((a, b))
        return runs

    def p90(self, start: float, end: float) -> Optional[float]:
        """Nível que o trecho alcança, sem se deixar levar por um estalo isolado."""
        first = max(0, int(start / self.step))
        last = min(len(self.levels), int(np.ceil(end / self.step)))
        if last <= first:
            return None
        return float(np.percentile(self.levels[first:last], 90))


def _rms_levels(audio_path: str) -> np.ndarray:
    """Lê o WAV do pipeline (PCM 16 bits, ver services/downloader.py) em blocos."""
    with wave.open(audio_path, "rb") as source:
        if source.getsampwidth() != 2:
            raise ValueError(f"esperava PCM de 16 bits, veio {source.getsampwidth() * 8}")
        channels = source.getnchannels()
        block = max(1, int(_RMS_STEP * source.getframerate()))
        chunks: list[np.ndarray] = []
        leftover = np.empty(0, dtype=np.float32)
        while True:
            raw = source.readframes(block * _RMS_BLOCKS_PER_READ)
            if not raw:
                break
            samples = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
            if channels > 1:
                samples = samples.reshape(-1, channels).mean(axis=1)
            samples = np.concatenate((leftover, samples))
            whole = len(samples) // block
            leftover = samples[whole * block:]
            blocks = samples[: whole * block].reshape(-1, block)
            rms = np.sqrt((blocks**2).mean(axis=1))
            chunks.append(20 * np.log10(np.maximum(rms, 10 ** (_RMS_FLOOR_DB / 20))))

    return np.concatenate(chunks) if chunks else np.empty(0, dtype=np.float32)


def measure_levels(job_id: str, audio_path: str, words: list[dict]) -> Optional[AudioLevels]:
    """
    O nível do áudio do vídeo, ou None se não der para medir.

    Nunca levanta, como `detect_gaps`: sem isto o corte volta a confiar só nos
    timestamps, o que é pior mas não é motivo para derrubar um job.
    """
    try:
        levels = _rms_levels(audio_path)
    except (OSError, EOFError, ValueError, wave.Error) as exc:
        logger.warning(f"[{job_id}] Sem nível fino de áudio ({exc}) — cortes só pelos timestamps")
        return None

    spoken: list[np.ndarray] = []
    for word in words:
        if word["end"] - word["start"] < _MIN_WORD_FOR_REFERENCE:
            continue
        first = int(word["start"] / _RMS_STEP)
        last = int(np.ceil(word["end"] / _RMS_STEP))
        spoken.append(levels[first:last])

    sample = np.concatenate(spoken) if spoken else np.empty(0)
    sample = sample[sample > _SILENCE_FLOOR]
    if len(sample) < 50:
        logger.warning(f"[{job_id}] Fala insuficiente para calibrar — cortes só pelos timestamps")
        return None

    return AudioLevels(levels=levels, speech_level=float(np.median(sample)))


def find_gaps(words: list[dict], min_gap: float = _MIN_GAP) -> list[tuple[float, float]]:
    """Trechos sem palavra transcrita entre uma palavra e a seguinte."""
    gaps: list[tuple[float, float]] = []
    for previous, current in zip(words, words[1:]):
        if current["start"] - previous["end"] >= min_gap:
            gaps.append((previous["end"], current["start"]))
    return gaps


def _percentile(values: list[float], fraction: float) -> float:
    ordered = sorted(values)
    index = min(len(ordered) - 1, int(len(ordered) * fraction))
    return ordered[index]


def _speech_level(timeline: list[tuple[float, float]], words: list[dict]) -> Optional[float]:
    """
    Nível de referência: a loudness mediana enquanto alguém fala.

    É contra isto que o buraco é comparado. Usar um limiar fixo em LUFS não
    funcionaria — cada vídeo tem sua própria mixagem, e o que interessa é o
    buraco ser alto *para aquele vídeo*.
    """
    spoken: list[float] = []
    index = 0
    for t, value in timeline:
        if value <= _SILENCE_FLOOR:
            continue
        while index < len(words) and words[index]["end"] < t:
            index += 1
        if index < len(words) and words[index]["start"] <= t <= words[index]["end"]:
            spoken.append(value)

    return median(spoken) if len(spoken) >= 50 else None


async def detect_gaps(job_id: str, audio_path: str, words: list[dict]) -> list[Gap]:
    """
    Os buracos da transcrição, cada um classificado pelo áudio.

    Nunca levanta: esta é uma camada de contexto extra, e um vídeo com áudio
    estranho deve continuar sendo analisado como antes — sem as anotações, com
    o modelo decidindo só pelo texto.
    """
    raw_gaps = find_gaps(words)
    if not raw_gaps:
        return []

    try:
        timeline = await loudness_timeline(audio_path)
    except (RuntimeError, OSError, FileNotFoundError) as exc:
        logger.warning(f"[{job_id}] Sem leitura de loudness ({exc}) — análise só pelo texto")
        return []

    if not timeline:
        logger.warning(f"[{job_id}] ebur128 não devolveu amostras — análise só pelo texto")
        return []

    speech = _speech_level(timeline, words)
    if speech is None:
        logger.warning(f"[{job_id}] Fala insuficiente para calibrar o nível — análise só pelo texto")
        return []

    gaps: list[Gap] = []
    cursor = 0
    # Onde termina o buraco anterior é onde a fala contínua atual começou.
    previous_end = 0.0
    for start, end in raw_gaps:
        while cursor < len(timeline) and timeline[cursor][0] < start:
            cursor += 1
        inside = []
        for t, value in timeline[cursor:]:
            if t > end:
                break
            inside.append(value)
        if not inside:
            previous_end = end
            continue
        gaps.append(Gap(
            start=start,
            end=end,
            loudness=_percentile(inside, 0.9),
            speech_level=speech,
            buildup_start=previous_end,
        ))
        previous_end = end

    events = [g for g in gaps if g.is_event]
    logger.info(
        f"[{job_id}] {len(gaps)} buraco(s) na transcrição, {len(events)} com áudio "
        f"de evento (fala em {speech:.1f} LUFS)"
    )
    for gap in events:
        logger.info(
            f"[{job_id}]   evento em [{gap.start:.1f}-{gap.end:.1f}] "
            f"({gap.duration:.1f}s, {gap.above_speech:+.1f} dB vs fala)"
        )

    return gaps


# ─── Resgate do corte ──────────────────────────────────────────────────────────

def _preroll_start(words: list[dict], event_start: float) -> float:
    """
    Onde começa a fala que leva ao evento.

    Volta frase a frase a partir do evento enquanto couber no preroll e não
    houver outro buraco no meio — o buraco anterior é uma troca de assunto, e
    atravessá-lo traria contexto que não tem a ver com o momento.
    """
    before = [w for w in words if w["end"] <= event_start]
    if not before:
        return event_start

    start = event_start
    index = len(before) - 1
    while index >= 0:
        if event_start - before[index]["start"] > _PREROLL_MAX:
            break
        if index + 1 < len(before) and before[index + 1]["start"] - before[index]["end"] >= _MIN_GAP:
            break  # buraco no meio: o que vem antes é outro assunto
        start = before[index]["start"]
        index -= 1

    return start


def rescue_start(
    start: float,
    end: float,
    gaps: list[Gap],
    words: list[dict],
    max_duration: float,
) -> tuple[float, Optional[Gap]]:
    """
    Puxa o início do corte para antes do evento, com a fala que o prepara.

    Dois erros levam ao mesmo prejuízo, e os dois são tratados aqui:

    1. O corte começa DEPOIS do buraco barulhento — o modelo achou o primeiro
       texto disponível e começou ali, entregando a reação sem a causa.
    2. O corte começa EM CIMA do buraco — abre no meio da gargalhada, sem a
       fala que monta a piada. É o erro mais sutil, porque o clipe parece certo
       no papel: ele contém o evento inteiro. Só que quem assiste cai numa
       reação a algo que nunca foi apresentado.

    Nos dois casos o início volta para antes do buraco, mais o preroll de fala.
    Só encurta para caber no teto de duração, nunca corta o evento em si, e
    devolve o início original quando não há evento nenhum por perto.
    """
    def _matches(gap: "Gap") -> bool:
        if not gap.is_strong_event:
            return False
        depois = 0 <= start - gap.end <= _REACTION_TOLERANCE
        em_cima = gap.start <= start <= gap.start + _ONSET_TOLERANCE
        return depois or em_cima

    event = next((g for g in gaps if _matches(g)), None)
    if event is None:
        return start, None

    new_start = _preroll_start(words, event.start)

    if end - new_start > max_duration:
        # Não cabe tudo: sacrifica o preroll primeiro e, se ainda não couber, a
        # parte inicial do próprio evento — nunca o final, onde está a reação.
        new_start = max(new_start, end - max_duration)

    if new_start >= start:
        return start, None

    return new_start, event
