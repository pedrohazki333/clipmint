"""
Custo por vídeo: o número que decide se um cliente dá lucro.

Duas coisas sendo guardadas, e a segunda é a que mais dói se quebrar:

  1. **o custo bate com a fatura** — minutos e tokens reais, tarifas exatas,
     sem arredondar cedo (a tarifa de transcrição é 0,0035: uma casa a menos e
     ela some);
  2. **corrigir uma tarifa hoje não reescreve o mês passado.** O painel precisa
     continuar batendo com faturas já pagas; se o custo fosse recalculado na
     leitura, cada correção de câmbio mudaria o lucro histórico.

E o caso que a decisão do dono criou: job devolvido custa dinheiro e não gera
receita. O evento tem que deixar isso visível, não diluído.
"""

import asyncio
from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.database import Base
from app.models import CostConfig, Job, UsageEvent, User
from app.services import costs
from tests.conftest import SEM_POSTGRES, postgres_disponivel, postgres_url


@pytest.fixture
def factory(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'c.db'}")
    fabrica = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)

    async def montar():
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

    asyncio.run(montar())
    return fabrica


def rodar(factory, corpo):
    async def principal():
        async with factory() as db:
            return await corpo(db)

    return asyncio.run(principal())


def _config() -> CostConfig:
    """A configuração em memória, sem banco — o cálculo é uma função pura."""
    return CostConfig(id=1, **costs.CONFIG_PADRAO)


# ─── O cálculo ────────────────────────────────────────────────────────────────


def test_custo_de_um_video_tipico():
    """Duas horas de podcast, o caso que este produto processa todo dia."""
    custo = costs.calcular(
        _config(),
        transcription_minutes=120,
        transcription_provider="assemblyai",
        analysis_model="claude-sonnet-4-6",
        input_tokens=43_000,
        output_tokens=3_000,
    )

    # 120 min x 0,0035
    assert custo.transcription_cost_usd == Decimal("0.420000")
    # 43k x 3,00/Mtok + 3k x 15,00/Mtok = 0,129 + 0,045
    assert custo.analysis_cost_usd == Decimal("0.174000")
    assert custo.storage_cost_usd == Decimal("0.005000")
    assert custo.total_cost_usd == Decimal("0.599000")
    # x 5,40
    assert custo.total_cost_brl == Decimal("3.2346")


def test_tarifa_pequena_nao_some_no_arredondamento():
    """0,0035 por minuto: arredondar a dois centavos zeraria a transcrição."""
    custo = costs.calcular(
        _config(),
        transcription_minutes=1,
        transcription_provider="assemblyai",
        analysis_model="claude-sonnet-4-6",
        input_tokens=0,
        output_tokens=0,
        cobrar_storage=False,
    )
    assert custo.transcription_cost_usd == Decimal("0.003500")
    assert custo.total_cost_usd == Decimal("0.003500")


def test_o_modelo_que_rodou_e_o_que_e_cobrado():
    """Sonnet e Opus não custam o mesmo — 3/15 contra 5/25."""
    sonnet = costs.calcular(
        _config(),
        transcription_minutes=0,
        transcription_provider="assemblyai",
        analysis_model="claude-sonnet-4-6",
        input_tokens=1_000_000,
        output_tokens=0,
        cobrar_storage=False,
    )
    opus = costs.calcular(
        _config(),
        transcription_minutes=0,
        transcription_provider="assemblyai",
        analysis_model="claude-opus-4-8",
        input_tokens=1_000_000,
        output_tokens=0,
        cobrar_storage=False,
    )
    assert sonnet.analysis_cost_usd == Decimal("3.000000")
    assert opus.analysis_cost_usd == Decimal("5.000000")


def test_modelo_sem_tarifa_fica_marcado_em_vez_de_sumir():
    """Zerar em silêncio subestima o custo — e custo baixo demais faz aceitar cliente deficitário."""
    custo = costs.calcular(
        _config(),
        transcription_minutes=10,
        transcription_provider="assemblyai",
        analysis_model="claude-modelo-que-nao-cadastrei",
        input_tokens=50_000,
        output_tokens=5_000,
    )
    assert custo.analysis_cost_usd == Decimal("0")
    assert custo.rate_snapshot["analysis_rate_missing"] is True
    # A transcrição continua contando: só a análise ficou sem tarifa.
    assert custo.transcription_cost_usd == Decimal("0.035000")


def test_provedor_diferente_do_cotado_fica_marcado():
    custo = costs.calcular(
        _config(),
        transcription_minutes=10,
        transcription_provider="deepgram",
        analysis_model="claude-sonnet-4-6",
        input_tokens=0,
        output_tokens=0,
    )
    assert custo.rate_snapshot["transcription_rate_mismatch"] is True
    # Aproximado, mas não zero.
    assert custo.transcription_cost_usd > 0


def test_snapshot_carrega_as_tarifas_usadas():
    custo = costs.calcular(
        _config(),
        transcription_minutes=1,
        transcription_provider="assemblyai",
        analysis_model="claude-sonnet-4-6",
        input_tokens=1,
        output_tokens=1,
    )
    s = custo.rate_snapshot
    assert s["analysis_model"] == "claude-sonnet-4-6"
    assert s["llm_input_usd_per_mtok"] == "3.0"
    assert s["fx_usd_brl"] == "5.40"
    assert "analysis_rate_missing" not in s


# ─── O histórico não se reescreve ─────────────────────────────────────────────


def test_mudar_a_tarifa_nao_mexe_no_evento_ja_gravado(factory):
    """É a razão de existir do rate_snapshot."""

    async def corpo(db):
        config = await costs.get_config(db)
        custo = costs.calcular(
            config,
            transcription_minutes=100,
            transcription_provider="assemblyai",
            analysis_model="claude-sonnet-4-6",
            input_tokens=0,
            output_tokens=0,
        )
        db.add(
            UsageEvent(
                id="ev1",
                total_cost_usd=custo.total_cost_usd,
                total_cost_brl=custo.total_cost_brl,
                rate_snapshot=custo.rate_snapshot,
                status="success",
                credits_charged=100,
            )
        )
        await db.commit()

        # O dólar dispara e a AssemblyAI reprecifica.
        await costs.update_config(
            db,
            fx_usd_brl=Decimal("7.00"),
            assemblyai_usd_per_min=Decimal("0.0100"),
        )
        await db.commit()

        evento = await db.scalar(select(UsageEvent).where(UsageEvent.id == "ev1"))
        # 100 min x 0,0035 = 0,35, mais 0,005 de storage = 0,355; x 5,40.
        assert evento.total_cost_brl == Decimal("1.9170")
        assert evento.rate_snapshot["fx_usd_brl"] == "5.40"

        # E o próximo evento já nasce com a tarifa nova.
        nova = await costs.get_config(db)
        proximo = costs.calcular(
            nova,
            transcription_minutes=100,
            transcription_provider="assemblyai",
            analysis_model="claude-sonnet-4-6",
            input_tokens=0,
            output_tokens=0,
        )
        assert proximo.rate_snapshot["fx_usd_brl"] == "7.00"

    rodar(factory, corpo)


def test_alterar_campo_desconhecido_e_recusado(factory):
    async def corpo(db):
        with pytest.raises(ValueError):
            await costs.update_config(db, margem_secreta=1)

    rodar(factory, corpo)


# ─── O prejuízo que o dono quer enxergar ──────────────────────────────────────


def test_job_devolvido_fica_visivel_como_custo_sem_receita(factory):
    """Custo > 0 e créditos cobrados = 0. É essa combinação que o painel soma."""

    async def corpo(db):
        db.add_all(
            [
                UsageEvent(
                    id="ok",
                    status="success",
                    total_cost_brl=Decimal("3.2346"),
                    credits_charged=120,
                ),
                UsageEvent(
                    id="quebrou",
                    status="failed",
                    total_cost_brl=Decimal("2.2680"),
                    credits_charged=0,
                ),
                UsageEvent(
                    id="apagado",
                    status="deleted",
                    total_cost_brl=Decimal("1.1340"),
                    credits_charged=0,
                ),
            ]
        )
        await db.commit()

        prejuizo = await db.scalar(
            select(UsageEvent.total_cost_brl)
            .where(UsageEvent.credits_charged == 0, UsageEvent.total_cost_brl > 0)
            .order_by(UsageEvent.total_cost_brl.desc())
            .limit(1)
        )
        assert prejuizo == Decimal("2.2680")

        todos = (
            await db.execute(
                select(UsageEvent).where(UsageEvent.credits_charged == 0)
            )
        ).scalars().all()
        # Falha e exclusão ficam separadas: a causa é diferente.
        assert {e.status for e in todos} == {"failed", "deleted"}

    rodar(factory, corpo)


def test_um_video_um_evento(factory):
    """Retomada ou caminho terminal disparado duas vezes não conta o custo em dobro."""

    async def corpo(db):
        user = User(email="a@b.c", password_hash="x")
        db.add(user)
        await db.flush()
        db.add(Job(id="j1", youtube_url="u", status="done", user_id=user.id))
        await db.flush()

        db.add(UsageEvent(id="e1", job_id="j1", user_id=user.id, status="success"))
        await db.commit()

        db.add(UsageEvent(id="e2", job_id="j1", user_id=user.id, status="success"))
        with pytest.raises(IntegrityError):
            await db.commit()

    rodar(factory, corpo)


@pytest.mark.skipif(not postgres_disponivel(), reason=SEM_POSTGRES)
def test_evento_sobrevive_ao_job_apagado():
    """Registro financeiro não some porque o usuário limpou a lista de jobs.

    Roda em Postgres porque é lá que a garantia existe: o SQLite só aplica
    chave estrangeira com `PRAGMA foreign_keys` ligado, e este projeto nunca
    liga (ver a migração 0007). Verificar isto em SQLite seria verificar nada.
    """
    from sqlalchemy import delete

    async def principal():
        engine = create_async_engine(postgres_url())
        fabrica = async_sessionmaker(
            bind=engine, class_=AsyncSession, expire_on_commit=False
        )
        marca = uuid4().hex[:8]
        async with fabrica() as db:
            user = User(email=f"custo-{marca}@teste.local", password_hash="x")
            db.add(user)
            await db.flush()
            db.add(Job(id=f"job-{marca}", youtube_url="u", status="done", user_id=user.id))
            await db.flush()
            db.add(
                UsageEvent(
                    id=f"ev-{marca}",
                    job_id=f"job-{marca}",
                    user_id=user.id,
                    status="success",
                    total_cost_brl=Decimal("3.0000"),
                )
            )
            await db.commit()
            user_id = user.id

        try:
            async with fabrica() as db:
                await db.execute(delete(Job).where(Job.id == f"job-{marca}"))
                await db.commit()

            async with fabrica() as db:
                evento = await db.scalar(
                    select(UsageEvent).where(UsageEvent.id == f"ev-{marca}")
                )
                assert evento is not None, "o evento foi apagado junto com o job"
                assert evento.total_cost_brl == Decimal("3.0000")
                assert evento.job_id is None, "o elo devia ter sido anulado, não mantido"
        finally:
            async with fabrica() as db:
                await db.execute(delete(UsageEvent).where(UsageEvent.id == f"ev-{marca}"))
                await db.execute(delete(Job).where(Job.id == f"job-{marca}"))
                await db.execute(delete(User).where(User.id == user_id))
                await db.commit()
            await engine.dispose()

    asyncio.run(principal())


# ─── A migração ───────────────────────────────────────────────────────────────


def test_o_banco_migrado_e_o_do_codigo_nascem_iguais(tmp_path, monkeypatch):
    """Duas origens de banco novo, uma configuração só.

    A migração escreve os valores literalmente (migração não importa código da
    aplicação) e o serviço tem a sua cópia. Divergirem em silêncio faria o custo
    depender de por qual caminho o banco veio.
    """
    from sqlalchemy import create_engine

    from app import db_migrations

    destino = tmp_path / "mig.db"
    engine = create_async_engine(f"sqlite+aiosqlite:///{destino}")
    monkeypatch.setattr(db_migrations, "engine", engine)
    asyncio.run(db_migrations.upgrade_to_head())
    asyncio.run(engine.dispose())

    sinc = create_engine(f"sqlite:///{destino}")
    try:
        with sinc.connect() as conn:
            linha = conn.execute(select(CostConfig)).mappings().one()
    finally:
        sinc.dispose()

    padrao = costs.CONFIG_PADRAO
    assert linha["llm_rates"] == padrao["llm_rates"]
    for campo in (
        "assemblyai_usd_per_min",
        "storage_usd_per_video",
        "fx_usd_brl",
        "fx_eur_brl",
        "fixed_cost_brl_month",
        "tax_pct_on_revenue",
        "gateway_fee_pct",
    ):
        assert float(linha[campo]) == float(padrao[campo]), campo
