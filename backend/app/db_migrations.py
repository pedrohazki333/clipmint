"""
Aplicação das migrações no startup.

Rodar `alembic upgrade head` sozinho não serve para este projeto por um motivo
concreto: existem bancos ANTERIORES ao Alembic. O de desenvolvimento tem todas
as tabelas, criadas pelo `create_all` + `ALTER TABLE` manual que havia antes, e
nenhuma linha em `alembic_version`. Para o Alembic, um banco assim está na
estaca zero — e o `upgrade head` tentaria `CREATE TABLE jobs`, que já existe,
e falharia no startup.

A saída é carimbar: reconhecer "este banco já está no estado da 0001" e gravar
isso, para o upgrade seguir dali. É por isso que a 0001 descreve o schema
antigo e a criação de `users` ficou separada na 0002 — se `users` estivesse na
0001, carimbar pularia a criação dela.

O carimbo é automático porque o alternativo é um passo manual documentado que
alguém vai esquecer, e o sintoma (servidor não sobe) aparece no pior momento.
"""

import logging

from alembic import command
from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from sqlalchemy import inspect
from pathlib import Path

from app.database import engine

logger = logging.getLogger(__name__)

_BACKEND_DIR = Path(__file__).resolve().parents[1]

#: Revisão que descreve o schema pré-Alembic.
BASELINE = "0001_schema_inicial"

#: Se esta tabela existe, o banco não é novo.
_TABELA_SENTINELA = "jobs"


def alembic_config(connection=None) -> Config:
    cfg = Config(str(_BACKEND_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(_BACKEND_DIR / "migrations"))
    if connection is not None:
        # Reusa a conexão do app: sem isto o Alembic abriria um segundo engine
        # e, no SQLite, dois escritores no mesmo arquivo se bloqueiam.
        cfg.attributes["connection"] = connection
    return cfg


def _estampar_se_preciso(connection) -> None:
    """Carimba a baseline num banco que já existia antes do Alembic."""
    contexto = MigrationContext.configure(connection)
    if contexto.get_current_revision() is not None:
        return  # já é gerenciado pelo Alembic

    tabelas = set(inspect(connection).get_table_names())
    if _TABELA_SENTINELA not in tabelas:
        return  # banco novo: o upgrade cria tudo do zero

    logger.warning(
        "Banco anterior ao Alembic detectado (tem '%s' e não tem alembic_version). "
        "Carimbando como %s — o schema antigo é exatamente o que essa revisão "
        "descreve — e seguindo com as migrações seguintes.",
        _TABELA_SENTINELA,
        BASELINE,
    )
    command.stamp(alembic_config(connection), BASELINE)


def _upgrade(connection) -> None:
    _estampar_se_preciso(connection)
    command.upgrade(alembic_config(connection), "head")


async def upgrade_to_head() -> None:
    """Deixa o banco na última revisão, carimbando antes se for o caso."""
    async with engine.begin() as conn:
        await conn.run_sync(_upgrade)
    logger.info("Migrações aplicadas: banco na revisão head.")
