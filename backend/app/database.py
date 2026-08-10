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
_ADDED_COLUMNS = [
    ("jobs", "layout_mode", "VARCHAR DEFAULT 'cover'"),
    ("jobs", "facecam_rect", "TEXT"),
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


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """Dependency do FastAPI para injetar sessão do banco."""
    async with AsyncSessionLocal() as session:
        try:
            yield session
        finally:
            await session.close()
