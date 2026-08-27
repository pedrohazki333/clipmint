"""
Consumo de crédito: a reserva, a reconciliação, e o job que não nasce sem saldo.

O bloqueio por saldo É a trava de custo do produto — substituiu a cota por
janela. Então o que estes testes guardam é, em ordem de gravidade:

  1. **sem saldo o job não existe** (nem a linha no banco: senão sobraria job
     órfão que ninguém processa e que conta como trabalho pedido);
  2. **a reserva sai do saldo na hora**, senão dez jobs disparados juntos
     passariam todos com crédito para um;
  3. **toda saída devolve a reserva** — sucesso, erro, exclusão e restart. Um
     caminho terminal esquecido deixa crédito preso para sempre.
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
from app.models import BillingConfig, CreditLedger, Job, User
from app.routers import jobs as jobs_router
from app.services import credits, quota, usage

URL = "https://www.youtube.com/watch?v=abcdefghijk"


def _config(bonus: int) -> dict:
    return {
        "id": 1,
        "credito_avulso_brl": Decimal("0.10"),
        "pacotes": [{"creditos": 300, "preco_brl": None}],
        "planos": [],
        "creditos_gratis_cadastro": bonus,
        "saldo_baixo_threshold": 120,
    }


@pytest.fixture
def ambiente(tmp_path, monkeypatch):
    """Build público (= com cobrança), pipeline neutralizado, vídeo de 5 min."""
    monkeypatch.setattr(settings, "public_build", True)
    monkeypatch.setattr(settings, "clipmint_password", "")
    monkeypatch.setattr(settings, "storage_dir", str(tmp_path / "storage"))
    settings.ensure_dirs()

    # O pipeline de verdade sairia para a rede; aqui só interessa o que a
    # criação do job faz com o saldo.
    async def sem_pipeline(job_id, resume=False):
        return None

    monkeypatch.setattr(jobs_router, "run_pipeline", sem_pipeline)

    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'u.db'}")
    factory = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)

    def montar(bonus: int):
        async def _montar():
            async with engine.begin() as conn:
                await conn.run_sync(Base.metadata.create_all)
            async with factory() as s:
                s.add(BillingConfig(**_config(bonus)))
                await s.commit()

        asyncio.run(_montar())

    async def override_db():
        async with factory() as session:
            yield session

    app = FastAPI()
    register_routers(app)
    app.dependency_overrides[get_db] = override_db

    def preparar(bonus: int = 30):
        montar(bonus)
        cliente = TestClient(app)
        resp = cliente.post(
            "/api/auth/register",
            json={"email": "usuario@exemplo.com", "password": "uma-senha-bem-longa"},
        )
        assert resp.status_code == 201, resp.text
        return cliente

    return preparar, factory


async def _saldo(factory) -> int:
    async with factory() as db:
        return int(await db.scalar(select(User.credit_balance)) or 0)


async def _extrato(factory) -> list[tuple[str, int]]:
    async with factory() as db:
        linhas = (
            await db.execute(select(CreditLedger).order_by(CreditLedger.created_at))
        ).scalars().all()
        return [(l.tipo, l.amount) for l in linhas]


def _criar_job(cliente, url=URL):
    return cliente.post("/api/jobs", json={"youtube_url": url, "subtitle_mode": "none"})


# ─── O custo ──────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "segundos,esperado",
    [
        (0, 0),
        (1, 1),        # nunca de graça
        (59, 1),
        (60, 1),
        (61, 2),       # arredonda para cima: a fatura de transcrição também
        (7200, 120),   # duas horas, o vídeo típico deste produto
        (7205, 121),
    ],
)
def test_custo_em_creditos(segundos, esperado):
    assert usage.custo_em_creditos(segundos) == esperado


# ─── A reserva ────────────────────────────────────────────────────────────────


def test_criar_job_reserva_o_custo_estimado(ambiente):
    preparar, factory = ambiente
    cliente = preparar(bonus=30)

    assert _criar_job(cliente).status_code == 201

    # Vídeo de 5 min (o padrão do conftest) = 5 créditos segurados.
    assert asyncio.run(_saldo(factory)) == 25
    assert asyncio.run(_extrato(factory)) == [("bonus", 30), ("hold", -5)]


def test_sem_saldo_o_job_nao_chega_a_existir(ambiente):
    """402, e nenhuma linha no banco: job órfão contaria como trabalho pedido."""
    preparar, factory = ambiente
    cliente = preparar(bonus=3)  # o vídeo custa 5

    resp = _criar_job(cliente)
    assert resp.status_code == 402
    assert "Saldo insuficiente" in resp.json()["detail"]

    async def jobs():
        async with factory() as db:
            return (await db.execute(select(Job))).scalars().all()

    assert asyncio.run(jobs()) == []
    # E o saldo não foi tocado.
    assert asyncio.run(_saldo(factory)) == 3
    assert asyncio.run(_extrato(factory)) == [("bonus", 3)]


def test_a_reserva_impede_o_job_seguinte(ambiente):
    """É o hold que impede disparar vários jobs com saldo para um."""
    preparar, factory = ambiente
    cliente = preparar(bonus=12)  # dá para dois vídeos de 5, não para três

    assert _criar_job(cliente, URL + "1").status_code == 201
    assert _criar_job(cliente, URL + "2").status_code == 201
    terceiro = _criar_job(cliente, URL + "3")

    assert terceiro.status_code == 402
    assert asyncio.run(_saldo(factory)) == 2


def test_versao_pessoal_nao_reserva_nada(ambiente, monkeypatch):
    """Lá quem paga a conta de API é o dono, direto no provedor."""
    preparar, factory = ambiente
    cliente = preparar(bonus=0)
    monkeypatch.setattr(settings, "public_build", False)

    assert _criar_job(cliente).status_code == 201
    assert asyncio.run(_extrato(factory)) == []


# ─── A reconciliação ──────────────────────────────────────────────────────────


async def _reconciliar(factory, job_id, *, segundos, sucesso):
    async with factory() as db:
        await usage.reconciliar(
            db, job_id=job_id, segundos_reais=segundos, sucesso=sucesso
        )
        await db.commit()


def _job_id(factory) -> str:
    async def ler():
        async with factory() as db:
            return (await db.execute(select(Job.id))).scalars().one()

    return asyncio.run(ler())


def test_sucesso_devolve_a_reserva_e_cobra_o_real(ambiente):
    preparar, factory = ambiente
    cliente = preparar(bonus=30)
    _criar_job(cliente)
    jid = _job_id(factory)

    # Rodou e a mídia baixada tinha 3 minutos, não os 5 estimados.
    asyncio.run(_reconciliar(factory, jid, segundos=180, sucesso=True))

    assert asyncio.run(_extrato(factory)) == [
        ("bonus", 30),
        ("hold", -5),
        ("release", 5),
        ("debito", -3),
    ]
    # 30 - 3: a diferença entre estimativa e real voltou.
    assert asyncio.run(_saldo(factory)) == 27


def test_falha_devolve_tudo_e_nao_cobra(ambiente):
    preparar, factory = ambiente
    cliente = preparar(bonus=30)
    _criar_job(cliente)
    jid = _job_id(factory)

    asyncio.run(_reconciliar(factory, jid, segundos=180, sucesso=False))

    assert asyncio.run(_extrato(factory)) == [
        ("bonus", 30),
        ("hold", -5),
        ("release", 5),
    ]
    assert asyncio.run(_saldo(factory)) == 30


def test_video_maior_que_a_estimativa_cobra_o_reservado(ambiente):
    """Erro da nossa medição não vira cobrança surpresa."""
    preparar, factory = ambiente
    cliente = preparar(bonus=30)
    _criar_job(cliente)
    jid = _job_id(factory)

    # A consulta disse 5 min; a mídia tinha 50.
    asyncio.run(_reconciliar(factory, jid, segundos=3000, sucesso=True))

    assert asyncio.run(_extrato(factory))[-1] == ("debito", -5)
    assert asyncio.run(_saldo(factory)) == 25


def test_reconciliar_duas_vezes_nao_devolve_duas_vezes(ambiente):
    preparar, factory = ambiente
    cliente = preparar(bonus=30)
    _criar_job(cliente)
    jid = _job_id(factory)

    asyncio.run(_reconciliar(factory, jid, segundos=180, sucesso=True))
    asyncio.run(_reconciliar(factory, jid, segundos=180, sucesso=True))

    assert asyncio.run(_saldo(factory)) == 27
    assert len(asyncio.run(_extrato(factory))) == 4


def test_reserva_que_consumiu_todo_o_saldo_e_reconciliavel(ambiente):
    """A ordem release-antes-de-debito é o que faz este caso funcionar.

    Com saldo exatamente igual à reserva, o saldo durante o job é zero. Debitar
    antes de devolver tentaria ir a negativo e o lançamento seria RECUSADO — num
    job que já rodou, com o dinheiro já gasto.
    """
    preparar, factory = ambiente
    cliente = preparar(bonus=5)  # exatamente o custo do vídeo
    _criar_job(cliente)
    assert asyncio.run(_saldo(factory)) == 0

    asyncio.run(_reconciliar(factory, _job_id(factory), segundos=300, sucesso=True))

    assert asyncio.run(_saldo(factory)) == 0
    assert asyncio.run(_extrato(factory)) == [
        ("bonus", 5),
        ("hold", -5),
        ("release", 5),
        ("debito", -5),
    ]


def test_job_sem_reserva_nao_quebra_a_reconciliacao(ambiente):
    """Job criado antes desta fatia, ou da versão pessoal: não há o que fechar."""
    preparar, factory = ambiente
    preparar(bonus=0)

    asyncio.run(_reconciliar(factory, "job-que-nao-tem-reserva", segundos=60, sucesso=True))
    assert asyncio.run(_extrato(factory)) == []


# ─── Exclusão ─────────────────────────────────────────────────────────────────


def test_excluir_job_em_andamento_devolve_o_credito(ambiente):
    """Quem devolveria era o pipeline, e ele não vai mais rodar."""
    preparar, factory = ambiente
    cliente = preparar(bonus=30)
    _criar_job(cliente)
    jid = _job_id(factory)
    assert asyncio.run(_saldo(factory)) == 25

    assert cliente.delete(f"/api/jobs/{jid}").status_code in (200, 204)
    assert asyncio.run(_saldo(factory)) == 30


def test_excluir_job_concluido_nao_devolve_de_novo(ambiente):
    preparar, factory = ambiente
    cliente = preparar(bonus=30)
    _criar_job(cliente)
    jid = _job_id(factory)
    asyncio.run(_reconciliar(factory, jid, segundos=180, sucesso=True))
    assert asyncio.run(_saldo(factory)) == 27

    cliente.delete(f"/api/jobs/{jid}")
    assert asyncio.run(_saldo(factory)) == 27


def test_extrato_sobrevive_ao_job_apagado(ambiente):
    """Registro financeiro não some porque o usuário limpou a lista de jobs."""
    preparar, factory = ambiente
    cliente = preparar(bonus=30)
    _criar_job(cliente)
    jid = _job_id(factory)
    asyncio.run(_reconciliar(factory, jid, segundos=180, sucesso=True))

    cliente.delete(f"/api/jobs/{jid}")

    # Os quatro lançamentos continuam lá, e o id do job segue legível na
    # descrição mesmo com a chave estrangeira anulada.
    extrato = asyncio.run(_extrato(factory))
    assert len(extrato) == 4

    async def descricoes():
        async with factory() as db:
            return [
                l.descricao
                for l in (await db.execute(select(CreditLedger))).scalars().all()
            ]

    assert any(jid in (d or "") for d in asyncio.run(descricoes()))


# ─── A contabilidade nunca derruba o job ──────────────────────────────────────


def test_falha_ao_reconciliar_nao_propaga(monkeypatch):
    """Saldo por conciliar é recuperável; job marcado como erro por isso, não."""

    async def explode(*a, **kw):
        raise RuntimeError("banco fora do ar")

    monkeypatch.setattr(usage, "reconciliar", explode)
    # Não levanta.
    asyncio.run(usage.reconciliar_job("qualquer", sucesso=True))


# ─── A cota de janela saiu de cena ────────────────────────────────────────────


def test_cobranca_substitui_a_cota_de_janela(ambiente, monkeypatch):
    """Com saldo, recusar quem pagou seria pior que não ter limite."""
    preparar, _ = ambiente
    preparar(bonus=30)
    monkeypatch.setattr(settings, "public_quota_max_videos", 10)
    monkeypatch.setattr(settings, "public_quota_max_minutes", 300)
    monkeypatch.setattr(settings, "quota_max_videos", 0)
    monkeypatch.setattr(settings, "quota_max_minutes", 0)

    assert quota.quota_limits() == (0, 0)


# ─── Retomar ──────────────────────────────────────────────────────────────────
#
# O caso que quase passou batido. Um job que falha devolve a reserva e não cobra
# nada — certo, ninguém recebeu clip. Mas ele pode ser RETOMADO, e aí recebe. Se
# a reconciliação usar o `release` como sinal de "já resolvi este job", a
# conclusão bem-sucedida da retomada não cobra: basta falhar uma vez antes de
# dar certo para levar o vídeo de graça, e falhar é comum (rede, chave de API,
# restart no meio). O sinal certo é o `debito`.


def _marcar_duracao(factory, jid, segundos, status="error"):
    """Deixa o job no estado em que o botão Retomar aparece.

    `duration_seconds` é o que o pipeline grava depois do download — é dela que
    sai o preço da retomada. E o status precisa ser terminal: em `queued` o
    endpoint responde 409 antes de olhar saldo, que é o comportamento certo.
    """
    async def _gravar():
        async with factory() as db:
            job = await db.get(Job, jid)
            job.duration_seconds = segundos
            job.status = status
            await db.commit()

    asyncio.run(_gravar())


def test_job_retomado_com_sucesso_cobra(ambiente):
    """O teste que o furo teria reprovado."""
    preparar, factory = ambiente
    cliente = preparar(bonus=30)
    _criar_job(cliente)
    jid = _job_id(factory)

    # 1ª tentativa: quebrou na transcrição. Devolve tudo, não cobra.
    asyncio.run(_reconciliar(factory, jid, segundos=180, sucesso=False))
    assert asyncio.run(_saldo(factory)) == 30

    # Retomada: desta vez rodou até o fim e entregou os clips.
    asyncio.run(_reconciliar(factory, jid, segundos=180, sucesso=True))

    assert asyncio.run(_extrato(factory)) == [
        ("bonus", 30),
        ("hold", -5),
        ("release", 5),   # da falha
        ("debito", -3),   # da retomada — não existia antes desta correção
    ]
    assert asyncio.run(_saldo(factory)) == 27


def test_job_retomado_nao_devolve_a_reserva_de_novo(ambiente):
    """Devolver duas vezes seria pior que não cobrar: criaria crédito."""
    preparar, factory = ambiente
    cliente = preparar(bonus=30)
    _criar_job(cliente)
    jid = _job_id(factory)

    asyncio.run(_reconciliar(factory, jid, segundos=180, sucesso=False))
    asyncio.run(_reconciliar(factory, jid, segundos=180, sucesso=True))

    tipos = [t for t, _ in asyncio.run(_extrato(factory))]
    assert tipos.count("release") == 1


def test_falhar_duas_vezes_seguidas_continua_de_graca(ambiente):
    """Cobrar só quem recebeu: duas falhas não entregaram nada."""
    preparar, factory = ambiente
    cliente = preparar(bonus=30)
    _criar_job(cliente)
    jid = _job_id(factory)

    asyncio.run(_reconciliar(factory, jid, segundos=180, sucesso=False))
    asyncio.run(_reconciliar(factory, jid, segundos=180, sucesso=False))

    assert asyncio.run(_saldo(factory)) == 30
    assert [t for t, _ in asyncio.run(_extrato(factory))] == ["bonus", "hold", "release"]


def test_retomar_job_ja_cobrado_nao_cobra_de_novo(ambiente):
    """Re-renderizar um clip que falhou não é uma segunda compra do vídeo."""
    preparar, factory = ambiente
    cliente = preparar(bonus=30)
    _criar_job(cliente)
    jid = _job_id(factory)

    asyncio.run(_reconciliar(factory, jid, segundos=180, sucesso=True))
    asyncio.run(_reconciliar(factory, jid, segundos=180, sucesso=True))

    assert asyncio.run(_saldo(factory)) == 27
    assert [t for t, _ in asyncio.run(_extrato(factory))].count("debito") == 1


def test_saldo_gasto_durante_a_retomada_deixa_a_conta_devendo(ambiente):
    """O trabalho foi entregue: quem espera é o próximo job, não este.

    Entre a falha (que devolveu) e o fim da retomada, o crédito devolvido pode
    ter ido para outro vídeo. Deixar a conta negativa é o único desfecho que não
    dá o clip de graça — e o saldo negativo trava a criação seguinte sozinho.
    """
    preparar, factory = ambiente
    cliente = preparar(bonus=30)
    _criar_job(cliente)
    jid = _job_id(factory)

    asyncio.run(_reconciliar(factory, jid, segundos=180, sucesso=False))

    # O usuário gastou o saldo inteiro em outra coisa enquanto este renderizava.
    async def _zerar():
        async with factory() as db:
            uid = (await db.execute(select(User.id))).scalars().one()
            await credits.lancar(
                db, user_id=uid, tipo="ajuste", amount=-30, descricao="gastou fora"
            )
            await db.commit()

    asyncio.run(_zerar())
    asyncio.run(_reconciliar(factory, jid, segundos=180, sucesso=True))

    assert asyncio.run(_saldo(factory)) == -3
    assert [t for t, _ in asyncio.run(_extrato(factory))][-1] == "debito"


# ─── A porta do Retomar ───────────────────────────────────────────────────────


def test_retomar_sem_saldo_e_recusado_com_402(ambiente):
    """Recusa ANTES de renderizar, não na última linha da cobrança."""
    preparar, factory = ambiente
    cliente = preparar(bonus=5)
    _criar_job(cliente)
    jid = _job_id(factory)
    _marcar_duracao(factory, jid, 180)

    asyncio.run(_reconciliar(factory, jid, segundos=180, sucesso=False))

    async def _zerar():
        async with factory() as db:
            uid = (await db.execute(select(User.id))).scalars().one()
            await credits.lancar(
                db, user_id=uid, tipo="ajuste", amount=-5, descricao="gastou fora"
            )
            await db.commit()

    asyncio.run(_zerar())

    resp = cliente.post(f"/api/jobs/{jid}/retry")
    assert resp.status_code == 402, resp.text
    assert "3" in resp.json()["detail"]


def test_retomar_com_saldo_passa(ambiente):
    preparar, factory = ambiente
    cliente = preparar(bonus=30)
    _criar_job(cliente)
    jid = _job_id(factory)
    _marcar_duracao(factory, jid, 180)
    asyncio.run(_reconciliar(factory, jid, segundos=180, sucesso=False))

    assert cliente.post(f"/api/jobs/{jid}/retry").status_code == 202


def test_retomar_job_com_reserva_de_pe_nao_pede_saldo(ambiente):
    """Job morto no restart: já está pago adiantado, retomar é de graça.

    Sem esta exceção, um job interrompido cujo hold consumiu todo o saldo ficaria
    impossível de retomar — o saldo que faltaria é o que ele próprio segurou.
    """
    preparar, factory = ambiente
    cliente = preparar(bonus=5)   # exatamente a reserva: saldo fica em zero
    _criar_job(cliente)
    jid = _job_id(factory)
    _marcar_duracao(factory, jid, 300)

    assert asyncio.run(_saldo(factory)) == 0
    assert cliente.post(f"/api/jobs/{jid}/retry").status_code == 202


def test_retomar_job_ja_cobrado_nao_pede_saldo(ambiente):
    """Re-renderizar clip que falhou num job pago não cobra pedágio."""
    preparar, factory = ambiente
    cliente = preparar(bonus=30)
    _criar_job(cliente)
    jid = _job_id(factory)
    asyncio.run(_reconciliar(factory, jid, segundos=300, sucesso=True))
    _marcar_duracao(factory, jid, 300, status="done")

    async def _zerar():
        async with factory() as db:
            uid = (await db.execute(select(User.id))).scalars().one()
            await credits.lancar(
                db, user_id=uid, tipo="ajuste", amount=-25, descricao="gastou fora"
            )
            await db.commit()

    asyncio.run(_zerar())
    assert cliente.post(f"/api/jobs/{jid}/retry").status_code == 202


def test_versao_pessoal_retoma_sem_pedir_saldo(ambiente, monkeypatch):
    """Sem cobrança não há reserva, e sem reserva retomar não tem preço."""
    preparar, factory = ambiente
    cliente = preparar(bonus=30)
    _criar_job(cliente)
    jid = _job_id(factory)
    _marcar_duracao(factory, jid, 300)

    async def _sem_reserva():
        async with factory() as db:
            for l in (await db.execute(select(CreditLedger))).scalars().all():
                await db.delete(l)
            await db.commit()

    asyncio.run(_sem_reserva())
    assert cliente.post(f"/api/jobs/{jid}/retry").status_code == 202
