"""
Ambiente do Alembic.

Duas particularidades deste projeto:

  1. **A URL vem do app, não do alembic.ini.** O `.env` da raiz é a fonte única
     de configuração — ter a URL do banco escrita também no ini criaria uma
     segunda cópia para manter em sincronia, e migração aplicada no banco errado
     é o tipo de erro que só se descobre tarde.

  2. **Tabelas fora do `models.py` são ignoradas.** O banco de desenvolvimento
     tem `model_video_jobs`, resquício da geração de vídeo pelo Veo que foi
     abandonada, com 4 linhas dentro. Sem o filtro abaixo, o `--autogenerate`
     proporia `DROP TABLE` nela e a migração apagaria dado real sem avisar.
"""

import asyncio
from logging.config import fileConfig

from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

from alembic import context

# Modelos precisam estar importados para o metadata conhecer as tabelas.
from app.config import settings
from app.database import Base
from app import models  # noqa: F401

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata

#: Tabelas que existem no banco mas não no código, e que o Alembic não deve
#: mexer. Ver a docstring acima.
IGNORAR_TABELAS = {"model_video_jobs"}


def include_object(object_, name, type_, reflected, compare_to):
    """Decide o que entra no autogenerate."""
    if type_ == "table" and name in IGNORAR_TABELAS:
        return False
    return True


def _url() -> str:
    return settings.db_url


def run_migrations_offline() -> None:
    """Gera o SQL sem conectar (alembic upgrade --sql)."""
    context.configure(
        url=_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        include_object=include_object,
        # O SQLite não sabe ALTER COLUMN; o batch mode reescreve a tabela por
        # baixo. No Postgres não muda nada.
        render_as_batch=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        include_object=include_object,
        render_as_batch=True,
        # Sem isto, mudança só de tipo passa despercebida no autogenerate.
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    configuration = config.get_section(config.config_ini_section, {})
    configuration["sqlalchemy.url"] = _url()
    connectable = async_engine_from_config(
        configuration, prefix="sqlalchemy.", poolclass=pool.NullPool
    )
    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await connectable.dispose()


def run_migrations_online() -> None:
    """Roda as migrações.

    Quando o app já está rodando, ele passa a própria conexão em
    `config.attributes["connection"]` — é assim que o startup aplica migração
    sem abrir um segundo engine.
    """
    connectable = config.attributes.get("connection", None)
    if connectable is not None:
        do_run_migrations(connectable)
        return
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
