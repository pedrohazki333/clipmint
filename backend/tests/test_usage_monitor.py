"""
Instrumentação: o que cada vídeo custou, gravado no fim do processamento.

O que estes testes guardam:

  1. **custo parcial é a regra.** Um job pode morrer no download (não custou
     nada), depois da transcrição (custou os minutos) ou depois da análise
     (custou os dois). Cobrar tudo sempre infla; cobrar zero sempre esconde.
  2. **o prejuízo aparece.** Job devolvido tem custo > 0 e créditos cobrados 0 —
     foi para isso que o dono pediu o monitor.
  3. **medir nunca derruba o pipeline.** Um erro na contabilidade não pode
     transformar um vídeo pronto num job com erro.
"""

import asyncio
from decimal import Decimal

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config import settings
from app.database import Base, get_db
from app.main import register_routers
from app.models import BillingConfig, Job, Transcript, UsageEvent, User
from app.routers import jobs as jobs_router
from app.services import credits, usage, usage_monitor

URL = "https://www.youtube.com/watch?v=abcdefghijk"

CONFIG_COBRANCA = {
    "id": 1,
    "credito_avulso_brl": Decimal("0.12"),
    "pacotes": [{"creditos": 300, "preco_brl": None}],
    "planos": [],
    "creditos_gratis_cadastro": 200,
    "saldo_baixo_threshold": 120,
}


@pytest.fixture
def ambiente(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "public_build", True)
    monkeypatch.setattr(settings, "clipmint_password", "")
    monkeypatch.setattr(settings, "claude_model", "claude-sonnet-4-6")
    monkeypatch.setattr(settings, "transcription_provider", "assemblyai")
    monkeypatch.setattr(settings, "storage_dir", str(tmp_path / "storage"))
    settings.ensure_dirs()

    async def sem_pipeline(job_id, resume=False):
        return None

    monkeypatch.setattr(jobs_router, "run_pipeline", sem_pipeline)

    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'm.db'}")
    factory = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)

    async def montar():
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        async with factory() as s:
            s.add(BillingConfig(**CONFIG_COBRANCA))
            await s.commit()

    asyncio.run(montar())

    async def override_db():
        async with factory() as session:
            yield session

    app = FastAPI()
    register_routers(app)
    app.dependency_overrides[get_db] = override_db
    cliente = TestClient(app)
    assert (
        cliente.post(
            "/api/auth/register",
            json={"email": "dono@exemplo.com", "password": "uma-senha-bem-longa"},
        ).status_code
        == 201
    )
    return cliente, factory


async def _preparar_job(
    factory,
    *,
    job_id="j1",
    minutos=120,
    transcrito=True,
    tokens=(43_000, 3_000),
    cobrado=None,
):
    """Monta um job no estado que o teste quer, como o pipeline o deixaria."""
    async with factory() as db:
        user = (await db.execute(select(User))).scalars().first()
        db.add(
            Job(
                id=job_id,
                user_id=user.id,
                youtube_url=URL,
                status="done",
                duration_seconds=minutos * 60,
            )
        )
        await db.flush()

        if transcrito:
            db.add(
                Transcript(
                    job_id=job_id, full_text="oi", words_json_path="/tmp/x.json"
                )
            )
        if tokens:
            await usage_monitor.registrar_analise(
                db,
                job_id,
                model="claude-sonnet-4-6",
                input_tokens=tokens[0],
                output_tokens=tokens[1],
            )
        if cobrado:
            await credits.lancar(
                db,
                user_id=user.id,
                tipo="debito",
                amount=-cobrado,
                ref_usage_id=job_id,
                descricao="teste",
            )
        await db.commit()
        return user.id


async def _fechar(factory, job_id, status):
    async with factory() as db:
        evento = await usage_monitor.fechar(db, job_id, status=status)
        await db.commit()
        return evento


async def _evento(factory, job_id="j1") -> UsageEvent:
    async with factory() as db:
        return await db.scalar(select(UsageEvent).where(UsageEvent.job_id == job_id))


# ─── O caso normal ────────────────────────────────────────────────────────────


def test_video_processado_com_sucesso_registra_o_custo_real(ambiente):
    _, factory = ambiente
    user_id = asyncio.run(_preparar_job(factory, cobrado=120))
    asyncio.run(_fechar(factory, "j1", "success"))
    ev = asyncio.run(_evento(factory))

    assert ev.status == "success"
    assert ev.user_id == user_id
    assert ev.analysis_model == "claude-sonnet-4-6"
    assert ev.input_tokens == 43_000
    # 120 min x 0,0035 = 0,42 · 43k/3k no Sonnet = 0,174 · storage 0,005
    assert ev.total_cost_usd == Decimal("0.599000")
    assert ev.total_cost_brl == Decimal("3.2346")
    # O que o usuário pagou vem do ledger, não de um parâmetro.
    assert ev.credits_charged == 120
    assert ev.rate_snapshot["fx_usd_brl"] == "5.40"


def test_um_video_um_evento_mesmo_com_analise_antes(ambiente):
    """`registrar_analise` e `fechar` escrevem na MESMA linha."""
    _, factory = ambiente
    asyncio.run(_preparar_job(factory, cobrado=120))
    asyncio.run(_fechar(factory, "j1", "success"))

    async def contar():
        async with factory() as db:
            return len((await db.execute(select(UsageEvent))).scalars().all())

    assert asyncio.run(contar()) == 1


# ─── Custo parcial ────────────────────────────────────────────────────────────


def test_job_que_morreu_no_download_nao_custou_nada(ambiente):
    """`duration_seconds` existe desde a criação — não é prova de transcrição."""
    _, factory = ambiente
    asyncio.run(_preparar_job(factory, transcrito=False, tokens=None))
    asyncio.run(_fechar(factory, "j1", "failed"))
    ev = asyncio.run(_evento(factory))

    assert ev.transcription_cost_usd == Decimal("0")
    assert ev.storage_cost_usd == Decimal("0")
    assert ev.analysis_cost_usd == Decimal("0")
    assert ev.total_cost_brl == Decimal("0")
    # A duração do vídeo continua registrada: ela é informação, não cobrança.
    assert ev.source_minutes == Decimal("120.000")


def test_job_que_morreu_depois_da_transcricao_custa_so_ela(ambiente):
    _, factory = ambiente
    asyncio.run(_preparar_job(factory, transcrito=True, tokens=None))
    asyncio.run(_fechar(factory, "j1", "failed"))
    ev = asyncio.run(_evento(factory))

    assert ev.transcription_cost_usd == Decimal("0.420000")
    assert ev.storage_cost_usd == Decimal("0.005000")
    assert ev.analysis_cost_usd == Decimal("0")


def test_job_que_morreu_depois_da_analise_custa_os_dois(ambiente):
    _, factory = ambiente
    asyncio.run(_preparar_job(factory, transcrito=True))
    asyncio.run(_fechar(factory, "j1", "failed"))
    ev = asyncio.run(_evento(factory))

    assert ev.transcription_cost_usd == Decimal("0.420000")
    assert ev.analysis_cost_usd == Decimal("0.174000")


# ─── O prejuízo que o dono quer ver ───────────────────────────────────────────


def test_job_que_falhou_custa_e_nao_recebe(ambiente):
    """Custo > 0 e cobrado = 0: é essa combinação que o painel vai somar."""
    _, factory = ambiente
    asyncio.run(_preparar_job(factory, cobrado=None))
    asyncio.run(_fechar(factory, "j1", "failed"))
    ev = asyncio.run(_evento(factory))

    assert ev.status == "failed"
    assert ev.credits_charged == 0
    assert ev.total_cost_brl > 0


def test_excluir_job_em_andamento_deixa_o_custo_registrado(ambiente):
    """O gasto com transcrição não some junto com o job."""
    cliente, factory = ambiente
    asyncio.run(_preparar_job(factory, cobrado=None))

    assert cliente.delete("/api/jobs/j1").status_code in (200, 204)

    async def ler():
        async with factory() as db:
            return (await db.execute(select(UsageEvent))).scalars().all()

    eventos = asyncio.run(ler())
    assert len(eventos) == 1
    ev = eventos[0]
    assert ev.status == "deleted"
    assert ev.credits_charged == 0
    assert ev.total_cost_brl > 0
    # O job sumiu; o registro financeiro ficou, com o elo anulado.
    assert ev.source_video_url == URL


# ─── Não reabre, não derruba ──────────────────────────────────────────────────


def test_fechar_duas_vezes_nao_reescreve(ambiente, monkeypatch):
    _, factory = ambiente
    asyncio.run(_preparar_job(factory, cobrado=120))
    asyncio.run(_fechar(factory, "j1", "success"))

    # O dólar dispara entre uma chamada e outra.
    async def encarecer():
        async with factory() as db:
            from app.services import costs

            await costs.update_config(db, fx_usd_brl=Decimal("9.00"))
            await db.commit()

    asyncio.run(encarecer())
    asyncio.run(_fechar(factory, "j1", "failed"))

    ev = asyncio.run(_evento(factory))
    assert ev.status == "success"
    assert ev.total_cost_brl == Decimal("3.2346")


def test_job_inexistente_nao_cria_evento(ambiente):
    _, factory = ambiente
    assert asyncio.run(_fechar(factory, "nao-existe", "failed")) is None


def test_falha_ao_medir_nao_derruba_o_pipeline(monkeypatch):
    """Vídeo pronto não pode virar job com erro por causa da contabilidade."""

    async def explode(*a, **kw):
        raise RuntimeError("banco fora do ar")

    monkeypatch.setattr(usage_monitor, "fechar", explode)
    asyncio.run(usage_monitor.fechar_job("qualquer", status="success"))  # não levanta

    monkeypatch.setattr(usage_monitor, "registrar_analise", explode)
    asyncio.run(
        usage_monitor.registrar_analise_job(
            "qualquer", model="m", input_tokens=1, output_tokens=1
        )
    )  # não levanta


# ─── O par com a reconciliação de créditos ────────────────────────────────────


def test_o_cobrado_vem_do_ledger_depois_da_reconciliacao(ambiente):
    """A ordem importa: fechar antes da reconciliação leria cobrado = 0."""
    cliente, factory = ambiente
    resp = cliente.post(
        "/api/jobs", json={"youtube_url": URL, "subtitle_mode": "none"}
    )
    assert resp.status_code == 201
    job_id = resp.json()["id"]

    async def terminar():
        async with factory() as db:
            db.add(
                Transcript(job_id=job_id, full_text="oi", words_json_path="/tmp/x.json")
            )
            await usage.reconciliar(
                db, job_id=job_id, segundos_reais=300, sucesso=True
            )
            await usage_monitor.fechar(db, job_id, status="success")
            await db.commit()

    asyncio.run(terminar())
    ev = asyncio.run(_evento(factory, job_id))
    # O vídeo do conftest tem 5 minutos = 5 créditos.
    assert ev.credits_charged == 5
