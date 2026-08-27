"""
Perfis: criação, semeadura e a ponte com o que já existia.

O perfil não substitui o nicho — ele o embrulha. `jobs.source_type` continua
sendo o que o pipeline lê; o perfil é quem escolhe esse valor na criação do job
e guarda o resto (nome, ícone, defaults do formulário).

Por isso este módulo é fino de propósito: quase tudo que um perfil "faz" já era
feito pelo nicho, e continua sendo.
"""

import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.features import allowed_source_types, source_type_allowed
from app.models import Job, Profile, User

logger = logging.getLogger(__name__)

#: Como cada nicho vira um perfil na primeira vez. Os nomes e ícones repetem o
#: que a interface já mostrava para aquela conta — a semeadura não deve parecer
#: uma coisa nova aparecendo, e sim o que já existia ganhando um lugar.
SEMENTES: dict[str, dict[str, str]] = {
    "podcast": {
        "name": "Podcast",
        "avatar": "mic",
        "default_layout_mode": "cover",
        "default_subtitle_mode": "word_highlight",
    },
    "gameplay": {
        "name": "Gameplay",
        "avatar": "gamepad",
        "default_layout_mode": "streamer",
        "default_subtitle_mode": "word_highlight",
    },
    "siege": {
        "name": "Siege X",
        "avatar": "target",
        "default_layout_mode": "streamer",
        "default_subtitle_mode": "word_highlight",
    },
}

#: Ícones que a interface sabe desenhar. Chave, não arquivo: upload de avatar
#: seria funcionalidade nova, e não é disso que esta reorganização trata.
AVATARES = ("mic", "gamepad", "target", "person", "video", "sparkles")

DEFAULT_AVATAR = "person"


def valid_avatar(value: str | None) -> str:
    return value if value in AVATARES else DEFAULT_AVATAR


async def seed_profiles(db: AsyncSession, user: User) -> int:
    """
    Cria um perfil para cada nicho que este usuário já usou.

    Idempotente e conservadora: só semeia nicho que ESTE usuário já tem job, e
    só se ele ainda não tiver perfil daquele nicho. Quem nunca usou gameplay não
    ganha um perfil de gameplay vazio.

    Na versão pessoal isso faz as contas de sempre reaparecerem como perfis, com
    os jobs antigos dentro — que é o comportamento que não pode se perder.
    """
    existentes = set(
        (
            await db.execute(
                select(Profile.source_type).where(Profile.user_id == user.id)
            )
        ).scalars().all()
    )

    usados = set(
        (
            await db.execute(
                select(Job.source_type).where(Job.user_id == user.id).distinct()
            )
        ).scalars().all()
    )

    criados = 0
    for source in allowed_source_types():
        if source in existentes or source not in usados:
            continue
        semente = SEMENTES.get(source, {})
        db.add(
            Profile(
                user_id=user.id,
                name=semente.get("name", source.title()),
                source_type=source,
                avatar=semente.get("avatar", DEFAULT_AVATAR),
                default_layout_mode=semente.get("default_layout_mode", "cover"),
                default_subtitle_mode=semente.get(
                    "default_subtitle_mode", "word_highlight"
                ),
            )
        )
        criados += 1

    if criados:
        await db.commit()
        logger.info(f"{criados} perfil(is) semeado(s) para {user.email}")
    return criados


async def adopt_orphan_jobs(db: AsyncSession, user: User) -> int:
    """
    Liga jobs sem perfil ao perfil do mesmo nicho.

    O casamento é por `source_type`, que é exatamente o que definia a "conta"
    antes — então nenhum job muda de conta, ele só passa a ter um perfil que o
    aponta. Job cujo nicho não tem perfil fica sem, e continua visível: a
    listagem por perfil é um filtro, não uma exigência.
    """
    perfis = (
        await db.execute(select(Profile).where(Profile.user_id == user.id))
    ).scalars().all()
    if not perfis:
        return 0

    por_nicho = {p.source_type: p.id for p in perfis}
    adotados = 0
    for source, profile_id in por_nicho.items():
        resultado = await db.execute(
            Job.__table__.update()
            .where(
                Job.user_id == user.id,
                Job.profile_id.is_(None),
                Job.source_type == source,
            )
            .values(profile_id=profile_id)
        )
        adotados += resultado.rowcount or 0

    if adotados:
        await db.commit()
        logger.info(f"{adotados} job(s) ligado(s) a um perfil ({user.email})")
    return adotados


def check_source_type(source_type: str) -> None:
    """O nicho existe neste build? Levanta ValueError se não."""
    if not source_type_allowed(source_type):
        permitidos = ", ".join(allowed_source_types())
        raise ValueError(f"Nicho inválido: escolha um de {permitidos}")
