from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase
from typing import AsyncGenerator

from app.config import settings


engine = create_async_engine(
    settings.sqlite_url,
    echo=False,
    connect_args={"check_same_thread": False},
)

AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autocommit=False,
    autoflush=False,
)


class Base(DeclarativeBase):
    pass


# Colunas adicionadas depois que a tabela já existia. create_all() só cria
# tabelas novas — não altera as antigas — e o projeto não usa Alembic, então o
# startup completa as que faltam. (tabela, coluna, definição SQL)
# SQL rodado uma única vez, logo após a coluna ser criada. Serve para colunas
# cujo DEFAULT não descreve as linhas antigas — sem isso todo job de gameplay
# já existente viraria 'podcast' e o cronograma postaria na conta errada.
_BACKFILL = {
    ("jobs", "source_type"): (
        "UPDATE jobs SET source_type = 'gameplay' WHERE layout_mode = 'streamer'"
    ),
}

_ADDED_COLUMNS = [
    ("jobs", "layout_mode", "VARCHAR DEFAULT 'cover'"),
    ("jobs", "facecam_rect", "TEXT"),
    ("jobs", "source_type", "VARCHAR DEFAULT 'podcast'"),
    ("jobs", "clip_mode", "VARCHAR DEFAULT 'individual'"),
    ("jobs", "manual_clips", "TEXT"),
    ("jobs", "manual_mode", "VARCHAR DEFAULT 'only'"),
    ("clips", "hook_score", "FLOAT"),
    ("clips", "retention_score", "FLOAT"),
    ("clips", "shareability_score", "FLOAT"),
    ("clips", "loopability_score", "FLOAT"),
    ("clips", "comment_bait_score", "FLOAT"),
    ("clips", "verdict", "VARCHAR"),
    ("clips", "weak_points_json", "TEXT"),
    ("clips", "trim_reason", "TEXT"),
    ("clips", "segments_json", "TEXT"),
    # Desempenho real depois de postado. Sem DEFAULT de propósito: nulo
    # significa "ainda não medido", que não é a mesma coisa que zero.
    ("clips", "posted_at", "DATETIME"),
    ("clips", "views", "INTEGER"),
    ("clips", "completion_rate", "FLOAT"),
    ("clips", "likes", "INTEGER"),
    ("clips", "comments", "INTEGER"),
    ("clips", "shares", "INTEGER"),
    ("clips", "metrics_at", "DATETIME"),
    # Aprendizado por clipe solto, sem o vídeo de origem (ver models.py).
    # DEFAULT 'aligned' descreve corretamente as referências antigas: todas
    # foram criadas quando esse era o único modo que existia.
    ("reference_examples", "kind", "VARCHAR DEFAULT 'aligned'"),
    ("reference_examples", "source_type", "VARCHAR DEFAULT 'podcast'"),
    ("reference_examples", "forensics_json", "TEXT"),
]


async def init_db() -> None:
    """Cria as tabelas e aplica as colunas adicionadas depois."""
    from app import models  # noqa: F401 - garante que os modelos sejam registrados
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await conn.run_sync(_add_missing_columns)


def _add_missing_columns(conn) -> None:
    """ALTER TABLE idempotente para bancos criados antes destas colunas."""
    import logging

    from sqlalchemy import inspect, text

    logger = logging.getLogger(__name__)
    inspector = inspect(conn)
    tables = set(inspector.get_table_names())

    for table, column, ddl in _ADDED_COLUMNS:
        if table not in tables:
            continue  # acabou de ser criada por create_all, já tem a coluna
        existing = {c["name"] for c in inspector.get_columns(table)}
        if column in existing:
            continue
        conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {column} {ddl}"))
        logger.info(f"Migration: {table}.{column} added")

        backfill = _BACKFILL.get((table, column))
        if backfill:
            result = conn.execute(text(backfill))
            logger.info(
                f"Migration: {table}.{column} backfilled ({result.rowcount} linha(s))"
            )


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """Dependency do FastAPI para injetar sessão do banco."""
    async with AsyncSessionLocal() as session:
        try:
            yield session
        finally:
            await session.close()
