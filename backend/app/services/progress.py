"""
Quanto da etapa atual de cada job já andou — para a barra da tela.

Duas fontes, e a tela trata as duas do mesmo jeito:

- **Medida**: o download conta bytes (o yt-dlp diz quanto baixou de quanto), e
  a geração de clipes conta clipes prontos. `base` é a fração de verdade.
- **Pelo histórico**: transcrição, análise e o render de cada clipe não têm
  contador nenhum — a AssemblyAI e o modelo só respondem quando acabam. O que
  existe é quanto essas etapas levaram nos jobs anteriores, no `stage_log`.
  A partir daí a tela anda de `base` a `base + span` em `expected_seconds`, e
  desacelera se passar disso, sem nunca encher sozinha: quem enche é a etapa
  terminar de verdade.

Fica em memória, não no banco. O download atualiza dezenas de vezes por
segundo, de dentro da thread do yt-dlp, e gravar isso seria escrever no banco
para algo que vale por três segundos. Funciona porque o pipeline roda no mesmo
processo que responde a API (BackgroundTasks, um worker); com mais de um
worker, o processo que responde pode não ser o que roda o job, e a resposta
vem sem progresso — a tela continua funcionando, só sem a barra andando.
"""

from __future__ import annotations

import json
import logging
import statistics
import time
from dataclasses import dataclass
from datetime import datetime
from typing import Optional

from sqlalchemy import func, select

from app.database import AsyncSessionLocal
from app.models import Clip, Job

logger = logging.getLogger(__name__)


@dataclass
class _Marca:
    stage: str
    base: float
    span: float
    expected_seconds: Optional[float]
    started: float  # time.monotonic()


_estado: dict[str, _Marca] = {}


def set_exact(job_id: str, stage: str, fraction: float) -> None:
    """Uma fração medida. Nunca recua dentro da mesma etapa."""
    fraction = max(0.0, min(1.0, fraction))
    atual = _estado.get(job_id)
    if atual and atual.stage == stage and atual.span == 0 and fraction < atual.base:
        return
    _estado[job_id] = _Marca(stage, fraction, 0.0, None, time.monotonic())


def start_estimate(
    job_id: str, stage: str, base: float, span: float, expected_seconds: float
) -> None:
    """Começa um trecho sem contador: de `base` a `base + span` em ~`expected_seconds`."""
    _estado[job_id] = _Marca(
        stage,
        max(0.0, min(1.0, base)),
        max(0.0, min(1.0 - base, span)),
        max(1.0, expected_seconds),
        time.monotonic(),
    )


def clear(job_id: str) -> None:
    _estado.pop(job_id, None)


def snapshot(job_id: str, stage: str) -> Optional[dict]:
    """O progresso para a resposta da API — só se for da etapa em que o job está."""
    marca = _estado.get(job_id)
    if not marca or marca.stage != stage:
        return None
    return {
        "base": round(marca.base, 4),
        "span": round(marca.span, 4),
        "expected_seconds": marca.expected_seconds,
        # Decorrido, e não o instante de início: o relógio do navegador não
        # precisa concordar com o do servidor.
        "elapsed_seconds": round(time.monotonic() - marca.started, 2),
    }


# ─── Estimativas a partir do histórico ───────────────────────────────────────

# Sem histórico nenhum (instalação nova): segundos por minuto de vídeo, mais um
# fixo. Medidos a olho nos primeiros jobs; o histórico substitui assim que há.
_PADRAO = {
    "transcribing": (6.0, 15.0),
    "analyzing": (4.0, 25.0),
}
_PADRAO_POR_CLIPE = 45.0
_AMOSTRA = 30


def _duracoes(stage_log: str | list | None) -> dict[str, float] | None:
    """Segundos de cada etapa, ou None se o job passou duas vezes pela mesma (resume)."""
    if not stage_log:
        return None
    try:
        marcas = json.loads(stage_log) if isinstance(stage_log, str) else stage_log
    except json.JSONDecodeError:
        return None
    if not isinstance(marcas, list):
        return None
    vistos: set[str] = set()
    out: dict[str, float] = {}
    for atual, proxima in zip(marcas, marcas[1:]):
        s = atual["s"]
        if s in vistos:
            return None
        vistos.add(s)
        try:
            ini = datetime.fromisoformat(atual["at"])
            fim = datetime.fromisoformat(proxima["at"])
        except (KeyError, TypeError, ValueError):
            return None
        out[s] = (fim - ini).total_seconds()
    return out


async def expected_stage_seconds(stage: str, video_seconds: float | None) -> float:
    """Quanto `stage` deve levar para um vídeo desta duração, pelos jobs anteriores."""
    minutos = max(0.5, (video_seconds or 0) / 60)
    por_min, fixo = _PADRAO[stage]
    try:
        async with AsyncSessionLocal() as db:
            linhas = (
                await db.execute(
                    select(Job.stage_log, Job.duration_seconds)
                    .where(Job.status == "done", Job.duration_seconds > 0)
                    .order_by(Job.updated_at.desc())
                    .limit(_AMOSTRA)
                )
            ).all()
        razoes = []
        for log, dur in linhas:
            d = _duracoes(log)
            if d and stage in d and d[stage] > 0:
                razoes.append(d[stage] / max(0.5, dur / 60))
        if razoes:
            return max(5.0, statistics.median(razoes) * minutos)
    except Exception:  # noqa: BLE001 — estimar nunca pode derrubar o job
        logger.warning("Estimativa de %s pelo histórico falhou", stage, exc_info=True)
    return por_min * minutos + fixo


async def expected_clip_seconds() -> float:
    """Quanto o render de um clipe leva, pelos jobs anteriores."""
    try:
        async with AsyncSessionLocal() as db:
            jobs = (
                await db.execute(
                    select(Job.id, Job.stage_log)
                    .where(Job.status == "done")
                    .order_by(Job.updated_at.desc())
                    .limit(_AMOSTRA)
                )
            ).all()
            if not jobs:
                return _PADRAO_POR_CLIPE
            contagem = dict(
                (
                    await db.execute(
                        select(Clip.job_id, func.count(Clip.id))
                        .where(Clip.job_id.in_([j.id for j in jobs]))
                        .group_by(Clip.job_id)
                    )
                ).all()
            )
        por_clipe = []
        for job_id, log in jobs:
            d = _duracoes(log)
            n = contagem.get(job_id, 0)
            if d and d.get("clipping", 0) > 0 and n:
                por_clipe.append(d["clipping"] / n)
        if por_clipe:
            return max(5.0, statistics.median(por_clipe))
    except Exception:  # noqa: BLE001
        logger.warning("Estimativa de render pelo histórico falhou", exc_info=True)
    return _PADRAO_POR_CLIPE
