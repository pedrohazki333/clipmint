"""
Perfis — a camada que a nova organização consome.

Deliberadamente fina: um perfil guarda nome, ícone, rubrica base e os defaults
do formulário de geração. Ele NÃO guarda nada que o pipeline leia — quem o
pipeline lê é `jobs.source_type`, que o perfil preencheu na criação do job.

Por isso não há rota de "gerar a partir do perfil": a geração continua sendo o
`POST /api/jobs` de sempre, com o mesmo payload. O perfil só decide o que vem
preenchido nele.
"""

import logging
import shutil
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field, field_validator, model_validator
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.deps import current_user
from app.features import SourceTypeField
from app.layouts import LAYOUT_LABELS, layout_allowed, layouts_for
from app.models import Clip, Job, Profile, User
from app.services.branding import profile_dir
from app.services.profiles import valid_avatar

logger = logging.getLogger(__name__)

router = APIRouter(tags=["profiles"], prefix="/profiles")


class ProfileCreate(BaseModel):
    name: str = Field(min_length=1, max_length=60)
    source_type: SourceTypeField
    avatar: str | None = None
    # Sem default fixo: "cover" só serve a podcast. Omitido, cai no primeiro
    # layout que a rubrica escolhida aceita.
    default_layout_mode: Optional[str] = None
    default_subtitle_mode: str = "word_highlight"

    @field_validator("name")
    @classmethod
    def limpa_nome(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("Dê um nome ao perfil.")
        return v

    @model_validator(mode="after")
    def valida_layout_com_a_rubrica(self) -> "ProfileCreate":
        """O layout padrão precisa servir à rubrica do perfil.

        São dois campos, então a checagem só é possível depois de os dois
        existirem — daí ser um validador de modelo e não de campo. Omitido, o
        layout é preenchido com o primeiro que a rubrica aceita.
        """
        if self.default_layout_mode is None:
            self.default_layout_mode = layouts_for(self.source_type)[0]
            return self
        if not layout_allowed(self.default_layout_mode, self.source_type):
            permitidos = ", ".join(
                LAYOUT_LABELS[l][0] for l in layouts_for(self.source_type)
            )
            raise ValueError(
                f"Este layout não serve à rubrica escolhida. "
                f"Disponíveis: {permitidos}."
            )
        return self

    @field_validator("default_subtitle_mode")
    @classmethod
    def valida_legenda(cls, v: str) -> str:
        if v not in ("word_highlight", "traditional", "none"):
            raise ValueError("Modo de legenda inválido.")
        return v


class ProfileUpdate(ProfileCreate):
    """Mesma forma da criação: editar um perfil é reescrevê-lo por inteiro."""


class ProfileResponse(BaseModel):
    id: str
    name: str
    source_type: str
    avatar: str | None
    default_layout_mode: str
    default_subtitle_mode: str
    # Contagens que a tela de perfis mostra. Derivadas dos jobs e clips que já
    # existem — nenhum contador é mantido em coluna, para não haver dois números
    # que possam discordar.
    job_count: int = 0
    clip_count: int = 0
    last_generated_at: str | None = None

    model_config = {"from_attributes": True}


async def _do_usuario(profile_id: str, user: User, db: AsyncSession) -> Profile:
    """O perfil, se for desta pessoa. 404 se não for — nunca 403 (ver D40)."""
    perfil = (
        await db.execute(
            select(Profile).where(Profile.id == profile_id, Profile.user_id == user.id)
        )
    ).scalar_one_or_none()
    if not perfil:
        raise HTTPException(status_code=404, detail="Perfil não encontrado")
    return perfil


async def _com_contagens(
    perfis: List[Profile], user: User, db: AsyncSession
) -> List[ProfileResponse]:
    """Anexa jobs, clipes e data da última geração de cada perfil.

    Duas consultas agregadas para a lista inteira, não uma por perfil: a home
    mostra todos os perfis de uma vez e N+1 ali apareceria já com cinco.
    """
    if not perfis:
        return []

    ids = [p.id for p in perfis]

    jobs_por_perfil = {
        pid: (n, ultimo)
        for pid, n, ultimo in (
            await db.execute(
                select(Job.profile_id, func.count(Job.id), func.max(Job.created_at))
                .where(Job.profile_id.in_(ids))
                .group_by(Job.profile_id)
            )
        ).all()
    }

    clips_por_perfil = {
        pid: n
        for pid, n in (
            await db.execute(
                select(Job.profile_id, func.count(Clip.id))
                .join(Clip, Clip.job_id == Job.id)
                .where(Job.profile_id.in_(ids), Clip.status == "ready")
                .group_by(Job.profile_id)
            )
        ).all()
    }

    saida = []
    for p in perfis:
        n_jobs, ultimo = jobs_por_perfil.get(p.id, (0, None))
        resposta = ProfileResponse.model_validate(p)
        resposta.job_count = n_jobs
        resposta.clip_count = clips_por_perfil.get(p.id, 0)
        resposta.last_generated_at = ultimo.isoformat() if ultimo else None
        saida.append(resposta)
    return saida


@router.get("", response_model=List[ProfileResponse])
async def list_profiles(
    user: User = Depends(current_user),
    db: AsyncSession = Depends(get_db),
) -> List[ProfileResponse]:
    """Os perfis desta pessoa, do mais antigo para o mais novo."""
    perfis = (
        await db.execute(
            select(Profile)
            .where(Profile.user_id == user.id)
            .order_by(Profile.created_at)
        )
    ).scalars().all()
    return await _com_contagens(list(perfis), user, db)


@router.post("", response_model=ProfileResponse, status_code=201)
async def create_profile(
    payload: ProfileCreate,
    user: User = Depends(current_user),
    db: AsyncSession = Depends(get_db),
) -> ProfileResponse:
    perfil = Profile(
        user_id=user.id,
        name=payload.name,
        source_type=payload.source_type,
        avatar=valid_avatar(payload.avatar),
        default_layout_mode=payload.default_layout_mode,
        default_subtitle_mode=payload.default_subtitle_mode,
    )
    db.add(perfil)
    await db.commit()
    await db.refresh(perfil)
    logger.info(f"Perfil '{perfil.name}' criado ({perfil.source_type}) por {user.email}")
    return ProfileResponse.model_validate(perfil)


@router.get("/{profile_id}", response_model=ProfileResponse)
async def get_profile(
    profile_id: str,
    user: User = Depends(current_user),
    db: AsyncSession = Depends(get_db),
) -> ProfileResponse:
    perfil = await _do_usuario(profile_id, user, db)
    return (await _com_contagens([perfil], user, db))[0]


@router.put("/{profile_id}", response_model=ProfileResponse)
async def update_profile(
    profile_id: str,
    payload: ProfileUpdate,
    user: User = Depends(current_user),
    db: AsyncSession = Depends(get_db),
) -> ProfileResponse:
    """
    Reescreve o perfil.

    Mudar a rubrica base afeta os PRÓXIMOS jobs, nunca os antigos: cada job
    guardou o próprio `source_type` na criação, e é ele que o pipeline lê.
    """
    perfil = await _do_usuario(profile_id, user, db)
    perfil.name = payload.name
    perfil.source_type = payload.source_type
    perfil.avatar = valid_avatar(payload.avatar)
    perfil.default_layout_mode = payload.default_layout_mode
    perfil.default_subtitle_mode = payload.default_subtitle_mode
    await db.commit()
    await db.refresh(perfil)
    return ProfileResponse.model_validate(perfil)


@router.delete("/{profile_id}", status_code=204)
async def delete_profile(
    profile_id: str,
    user: User = Depends(current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    """
    Exclui o perfil — e SÓ ele.

    Os jobs e clipes que saíram dele ficam: eles são o trabalho, o perfil era só
    a configuração que os originou. Ficam com `profile_id` nulo, o mesmo estado
    dos jobs anteriores aos perfis, e seguem visíveis na biblioteca.

    Apagar os vídeos junto seria destruir trabalho para remover uma preferência.
    """
    perfil = await _do_usuario(profile_id, user, db)

    resultado = await db.execute(
        Job.__table__.update()
        .where(Job.profile_id == perfil.id)
        .values(profile_id=None)
    )
    await db.execute(delete(Profile).where(Profile.id == perfil.id))
    await db.commit()

    # Os presets deste perfil saem junto: eles só faziam sentido enquanto ele
    # existia, e sem isto cada perfil excluído deixaria uma pasta de imagens
    # órfã que nada mais aponta. Os clipes JÁ RENDERIZADOS não mudam — a marca
    # foi queimada no vídeo no momento do render.
    do_perfil = profile_dir(perfil.id)
    if do_perfil is not None and do_perfil.exists():
        shutil.rmtree(do_perfil, ignore_errors=True)
        logger.info(f"Presets do perfil '{perfil.name}' removidos de {do_perfil}")
    logger.info(
        f"Perfil '{perfil.name}' excluído; {resultado.rowcount or 0} job(s) "
        f"preservado(s) sem perfil"
    )
