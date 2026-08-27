"""
Conexão com o banco e aplicação das migrações.

O projeto fala dois dialetos, de propósito:

  - **SQLite** na versão pessoal e nos testes. É uma ferramenta local usada todo
    dia; exigir um Postgres no laptop para clipar um vídeo seria custo sem
    contrapartida, e os testes rodam em arquivo temporário sem serviço externo.
  - **Postgres** no build público. Um servidor multiusuário escrevendo num
    arquivo só corrompe sob concorrência, e é isso que o SQLite é.

O build público RECUSA subir em SQLite (ver `app/main.py`) — a escolha é
verificada, não confiada ao cuidado de quem faz o deploy.

Migrações são do Alembic. Antes havia uma lista de `ALTER TABLE` à mão aqui,
que funcionava só no SQLite: os tipos que ela emitia (`DATETIME`) nem existem no
Postgres, e a primeira migração num servidor de verdade teria falhado.
"""

import logging
from typing import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase

from app.config import settings

logger = logging.getLogger(__name__)


def _engine_kwargs() -> dict:
    """Argumentos que só fazem sentido para um dos dialetos.

    `check_same_thread` é exclusivo do SQLite e o Postgres recusa a conexão se
    ele for passado; o pool é o inverso, o SQLite não usa.
    """
    if settings.is_postgres:
        return {
            "pool_size": settings.db_pool_size,
            "max_overflow": settings.db_max_overflow,
            # Conexão que ficou parada em fila de proxy ou firewall morre em
            # silêncio; o pre_ping troca um round-trip barato por um erro
            # "server closed the connection" no meio de um job.
            "pool_pre_ping": True,
        }
    return {"connect_args": {"check_same_thread": False}}


engine = create_async_engine(settings.db_url, echo=False, **_engine_kwargs())

AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autocommit=False,
    autoflush=False,
)


class Base(DeclarativeBase):
    pass


async def init_db() -> None:
    """Deixa o banco na versão mais recente do schema."""
    from app import models  # noqa: F401 - registra os modelos no metadata
    from app.db_migrations import upgrade_to_head

    await upgrade_to_head()


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """Dependency do FastAPI para injetar sessão do banco."""
    async with AsyncSessionLocal() as session:
        try:
            yield session
        finally:
            await session.close()
