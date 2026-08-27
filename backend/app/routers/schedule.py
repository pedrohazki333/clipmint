"""
Seleção de clipes para o cronograma de postagem.

Cada horário do dia posta o clipe que lidera um eixo específico da rubrica —
07:00 o maior hook_score, 22:30 o maior loopability_score — e alterna entre as
contas. Este router é a ponte entre a análise e o
agendador: ele ordena os clipes prontos pelo eixo pedido.

O estado de "já postei esse" fica com o agendador; aqui basta mandar os ids já
usados em `exclude` para eles saírem da fila.
"""

import logging
from typing import Annotated, List, Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.features import SourceTypeField, allowed_source_types
from app.models import Clip, Job

logger = logging.getLogger(__name__)

router = APIRouter(tags=["schedule"])

# Eixo pedido → coluna que ordena. "overall" é o "mais equilibrado" do
# cronograma: a nota final ponderada, não um eixo isolado.
_AXIS_COLUMNS = {
    "hook": Clip.hook_score,
    "retention": Clip.retention_score,
    "shareability": Clip.shareability_score,
    "loopability": Clip.loopability_score,
    "comment_bait": Clip.comment_bait_score,
    "overall": Clip.virality_score,
}

Axis = Literal["hook", "retention", "shareability", "loopability", "comment_bait", "overall"]

# Grade de postagem: horário → (conta, eixo que escolhe o clipe).
# Fica aqui para o agendador não manter uma cópia divergente do mapa.
#
# As três contas seguem a mesma lógica de eixo por faixa do dia — gancho de
# manhã, retenção no meio, comentários no almoço, equilíbrio à tarde,
# compartilhamento no pico da noite, loop no fecho —, escalonadas para não
# publicar duas de uma vez.
ALL_POSTING_SLOTS = [
    ("07:00", "podcast", "hook"),
    ("08:30", "gameplay", "hook"),
    ("09:30", "siege", "hook"),
    ("10:30", "podcast", "retention"),
    ("12:00", "gameplay", "retention"),
    ("12:45", "siege", "retention"),
    ("13:30", "podcast", "comment_bait"),
    ("15:00", "gameplay", "comment_bait"),
    ("16:00", "siege", "comment_bait"),
    ("17:00", "podcast", "overall"),
    ("18:30", "gameplay", "overall"),
    ("19:15", "siege", "overall"),
    ("20:00", "podcast", "shareability"),
    ("21:30", "gameplay", "shareability"),
    ("22:00", "siege", "shareability"),
    ("22:30", "podcast", "loopability"),
    ("23:30", "gameplay", "loopability"),
    ("00:15", "siege", "loopability"),
]


def posting_slots() -> list[tuple[str, str, str]]:
    """A grade deste build.

    No build público os horários de Siege X somem da grade em vez de apontarem
    para uma conta que não existe — um agendador que lesse a grade completa
    ficaria pedindo clipes de um nicho sem nenhum job.
    """
    permitidos = allowed_source_types()
    return [slot for slot in ALL_POSTING_SLOTS if slot[1] in permitidos]


class SlotResponse(BaseModel):
    time: str
    source_type: str
    axis: str


class PickResponse(BaseModel):
    """Clipe candidato a um slot, com o contexto que o agendador precisa."""

    clip_id: str
    job_id: str
    axis: str
    axis_score: Optional[float]
    virality_score: float
    source_type: str
    video_title: Optional[str]
    channel_name: Optional[str]
    start_time: float
    end_time: float
    duration: float
    hook: Optional[str]
    suggested_title: Optional[str]
    verdict: Optional[str]
    file_path: Optional[str]


@router.get("/schedule/slots", response_model=List[SlotResponse])
async def list_slots() -> List[SlotResponse]:
    """A grade de horários e o eixo que decide o clipe de cada um."""
    return [
        SlotResponse(time=time, source_type=source, axis=axis)
        for time, source, axis in posting_slots()
    ]


@router.get("/schedule/pick", response_model=List[PickResponse])
async def pick_clips(
    # O Query vai DENTRO do Annotated: como valor default ele faria o FastAPI
    # descartar a validação de nicho que vem no SourceTypeField.
    axis: Annotated[Axis, Query(description="Eixo que ordena a fila")],
    source: Annotated[SourceTypeField, Query(description="Conta de destino do clipe")],
    limit: Annotated[int, Query(ge=1, le=50)] = 1,
    exclude: Annotated[
        Optional[str],
        Query(description="IDs de clipes já postados, separados por vírgula"),
    ] = None,
    db: AsyncSession = Depends(get_db),
) -> List[PickResponse]:
    """
    Clipes prontos da conta pedida, do maior para o menor no eixo escolhido.

    Só entram clipes renderizados (`status='ready'`) e analisados pela rubrica
    de cinco eixos. Clip antigo fica de fora até ser reanalisado — inclusive no
    `overall`, onde ele tem `virality_score` mas numa escala de outra rubrica:
    misturar as duas ordenações colocaria o clipe errado no ar.
    """
    column = _AXIS_COLUMNS[axis]
    excluded = {i.strip() for i in (exclude or "").split(",") if i.strip()}

    query = (
        select(Clip, Job)
        .join(Job, Clip.job_id == Job.id)
        .where(
            Clip.status == "ready",
            Job.source_type == source,
            column.is_not(None),
            # Marca de que o clip passou pela rubrica nova.
            Clip.hook_score.is_not(None),
        )
        .order_by(column.desc(), Clip.virality_score.desc())
    )
    if excluded:
        query = query.where(Clip.id.not_in(excluded))

    rows = (await db.execute(query.limit(limit))).all()

    return [
        PickResponse(
            clip_id=clip.id,
            job_id=job.id,
            axis=axis,
            axis_score=getattr(clip, f"{axis}_score", None) if axis != "overall" else clip.virality_score,
            virality_score=clip.virality_score,
            source_type=job.source_type or "podcast",
            video_title=job.video_title,
            channel_name=job.channel_name,
            start_time=clip.start_time,
            end_time=clip.end_time,
            duration=clip.duration,
            hook=clip.hook,
            suggested_title=clip.suggested_title,
            verdict=clip.verdict,
            file_path=clip.file_path,
        )
        for clip, job in rows
    ]
