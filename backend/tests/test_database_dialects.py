"""
O banco tem que funcionar nos dois dialetos, e o build público só num deles.

O projeto fala SQLite (versão pessoal e testes) e Postgres (build público). O
que quebra nesse arranjo é sutil: argumento de conexão que só um dialeto aceita,
tipo de coluna que só existe num deles, e a migração de um banco que nasceu
antes do Alembic.
"""

import pytest
from sqlalchemy import inspect

from app.config import settings
from app.database import _engine_kwargs
from app.main import _require_postgres_on_public_build


# ─── Argumentos de conexão por dialeto ────────────────────────────────────────

def test_sqlite_recebe_check_same_thread(monkeypatch):
    monkeypatch.setattr(settings, "sqlite_url", "")
    monkeypatch.setattr(settings, "database_url", "sqlite+aiosqlite:///./x.db")
    kwargs = _engine_kwargs()
    assert kwargs["connect_args"]["check_same_thread"] is False
    assert "pool_size" not in kwargs, "SQLite não usa pool"


def test_postgres_recebe_pool_e_nao_check_same_thread(monkeypatch):
    """
    `check_same_thread` é exclusivo do SQLite — o Postgres RECUSA a conexão.

    Era o argumento passado incondicionalmente antes desta fatia: a primeira
    tentativa de subir em Postgres teria morrido na conexão.
    """
    monkeypatch.setattr(settings, "sqlite_url", "")
    monkeypatch.setattr(settings, "database_url", "postgresql+psycopg://u:p@h/db")
    kwargs = _engine_kwargs()
    assert "connect_args" not in kwargs
    assert kwargs["pool_size"] == settings.db_pool_size
    assert kwargs["pool_pre_ping"] is True


# ─── A URL e a compatibilidade com o nome antigo ──────────────────────────────

def test_sqlite_url_antigo_continua_valendo(monkeypatch):
    """Um .env existente não pode parar de funcionar por causa do nome novo."""
    monkeypatch.setattr(settings, "sqlite_url", "sqlite+aiosqlite:///./antigo.db")
    monkeypatch.setattr(settings, "database_url", "postgresql+psycopg://u:p@h/db")
    assert settings.db_url == "sqlite+aiosqlite:///./antigo.db"
    assert settings.is_postgres is False


def test_database_url_vale_quando_o_antigo_esta_vazio(monkeypatch):
    monkeypatch.setattr(settings, "sqlite_url", "")
    monkeypatch.setattr(settings, "database_url", "postgresql+psycopg://u:p@h/db")
    assert settings.is_postgres is True


# ─── O build público exige Postgres ───────────────────────────────────────────

def test_publico_recusa_sqlite(monkeypatch):
    monkeypatch.setattr(settings, "public_build", True)
    monkeypatch.setattr(settings, "sqlite_url", "")
    monkeypatch.setattr(settings, "database_url", "sqlite+aiosqlite:///./x.db")
    with pytest.raises(RuntimeError, match="exige PostgreSQL"):
        _require_postgres_on_public_build()


def test_publico_aceita_postgres(monkeypatch):
    monkeypatch.setattr(settings, "public_build", True)
    monkeypatch.setattr(settings, "sqlite_url", "")
    monkeypatch.setattr(settings, "database_url", "postgresql+psycopg://u:p@h/db")
    _require_postgres_on_public_build()  # não levanta


def test_versao_pessoal_continua_em_sqlite(monkeypatch):
    """Exigir Postgres no laptop seria custo sem contrapartida."""
    monkeypatch.setattr(settings, "public_build", False)
    monkeypatch.setattr(settings, "sqlite_url", "")
    monkeypatch.setattr(settings, "database_url", "sqlite+aiosqlite:///./x.db")
    _require_postgres_on_public_build()  # não levanta


# ─── Migrações ────────────────────────────────────────────────────────────────

def _tabelas(url: str) -> set[str]:
    from sqlalchemy import create_engine

    engine = create_engine(url)
    try:
        with engine.connect() as conn:
            return set(inspect(conn).get_table_names())
    finally:
        engine.dispose()


def test_banco_novo_recebe_o_schema_completo(tmp_path, monkeypatch):
    import asyncio

    from sqlalchemy.ext.asyncio import create_async_engine

    from app import db_migrations

    destino = tmp_path / "novo.db"
    engine = create_async_engine(f"sqlite+aiosqlite:///{destino}")
    monkeypatch.setattr(db_migrations, "engine", engine)

    asyncio.run(db_migrations.upgrade_to_head())
    asyncio.run(engine.dispose())

    tabelas = _tabelas(f"sqlite:///{destino}")
    assert {"jobs", "clips", "transcripts", "users", "alembic_version"} <= tabelas


def _banco_pre_alembic(tmp_path, monkeypatch, extras_sql: list[str] | None = None):
    """
    Constrói um banco no estado "antes do Alembic" e roda o upgrade nele.

    O schema é o REAL — gerado pela própria 0001, que é a descrição fiel do que
    existia antes — e não uma versão simplificada à mão: a 0002 mexe em `jobs`
    com batch mode, que no SQLite recria a tabela a partir do que encontra, e
    uma tabela de mentira com colunas faltando falharia por motivo errado.

    Depois de montado, `alembic_version` é apagada: é exatamente assim que um
    banco criado pelo `create_all` antigo se apresenta.
    """
    import asyncio
    import sqlite3

    from sqlalchemy.ext.asyncio import create_async_engine

    from app import db_migrations

    caminho = tmp_path / "legado.db"
    engine = create_async_engine(f"sqlite+aiosqlite:///{caminho}")
    monkeypatch.setattr(db_migrations, "engine", engine)

    # 1. Schema antigo, via a revisão que o descreve.
    async def ate_0001():
        from alembic import command

        async with engine.begin() as conn:
            await conn.run_sync(
                lambda c: command.upgrade(db_migrations.alembic_config(c), "0001_schema_inicial")
            )

    asyncio.run(ate_0001())

    # 2. Dado dentro, e o que mais o teste precisar.
    raw = sqlite3.connect(caminho)
    raw.execute(
        "INSERT INTO jobs (id, youtube_url, layout_mode, source_type, status) "
        "VALUES ('antigo', 'u', 'streamer', 'gameplay', 'done')"
    )
    for sql in extras_sql or []:
        raw.execute(sql)
    # 3. Apaga o registro de versão: agora ele parece anterior ao Alembic.
    raw.execute("DELETE FROM alembic_version")
    raw.commit()
    raw.close()

    asyncio.run(db_migrations.upgrade_to_head())
    asyncio.run(engine.dispose())
    return caminho


def test_banco_anterior_ao_alembic_e_carimbado_e_nao_recriado(tmp_path, monkeypatch):
    """
    O caso que impede o servidor de subir se for tratado errado.

    Um banco criado pelo `create_all` antigo tem todas as tabelas e nenhuma
    linha em `alembic_version`. Para o Alembic ele está na estaca zero, e o
    `upgrade head` tentaria `CREATE TABLE jobs` — que já existe — e falharia.
    """
    import sqlite3

    caminho = _banco_pre_alembic(tmp_path, monkeypatch)

    raw = sqlite3.connect(caminho)
    # A linha antiga continua lá — carimbar não pode perder dado.
    assert raw.execute("SELECT COUNT(*) FROM jobs").fetchone()[0] == 1
    assert raw.execute("SELECT source_type FROM jobs").fetchone()[0] == "gameplay"
    # E o delta de usuários rodou por cima.
    colunas = {r[1] for r in raw.execute("PRAGMA table_info(jobs)")}
    assert "user_id" in colunas
    assert raw.execute(
        "SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name='users'"
    ).fetchone()[0] == 1
    # A revisão final é a última da cadeia, seja qual for — travar o nome aqui
    # faria toda migração nova quebrar um teste que não é sobre ela.
    from app.db_migrations import alembic_config
    from alembic.script import ScriptDirectory

    head = ScriptDirectory.from_config(alembic_config()).get_current_head()
    assert raw.execute("SELECT version_num FROM alembic_version").fetchone()[0] == head
    raw.close()


def test_tabela_fora_do_codigo_nao_e_apagada(tmp_path, monkeypatch):
    """
    `model_video_jobs` é resquício da geração pelo Veo, com dado real dentro.

    Sem o filtro de `IGNORAR_TABELAS` no env.py, o autogenerate proporia
    DROP TABLE nela e a migração apagaria dado sem avisar.
    """
    import sqlite3

    caminho = _banco_pre_alembic(
        tmp_path,
        monkeypatch,
        extras_sql=[
            "CREATE TABLE model_video_jobs (id VARCHAR PRIMARY KEY, nota VARCHAR)",
            "INSERT INTO model_video_jobs VALUES ('x', 'dado que nao pode sumir')",
        ],
    )

    raw = sqlite3.connect(caminho)
    assert raw.execute("SELECT nota FROM model_video_jobs").fetchone()[0] == (
        "dado que nao pode sumir"
    )
    raw.close()
