"""
Painel do dono: a fechadura, a fronteira do mês e a conta do lucro.

Em ordem de gravidade:

  1. **a porta é no backend.** Um usuário comum que descubra a URL tem que levar
     403 do servidor. Esconder na interface não é proteção.
  2. **a fronteira do mês é America/São_Paulo.** Em UTC, as três últimas horas
     do dia 31 caem no mês seguinte — e o painel deixaria de bater com o
     extrato do contador justamente na virada.
  3. **estimativa é marcada.** Taxa de gateway não informada e imposto
     placeholder voltam com aviso, senão viram fato no meio de um número.
"""

import asyncio
from datetime import datetime, timezone
from decimal import Decimal

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config import settings
from app.database import Base, get_db
from app.main import register_routers
from app.models import BillingConfig, Payment, Subscription, UsageEvent, User

MES = "2026-08"

CONFIG_COBRANCA = {
    "id": 1,
    "credito_avulso_brl": Decimal("0.12"),
    "pacotes": [{"creditos": 300, "preco_brl": None}],
    "planos": [],
    "creditos_gratis_cadastro": 0,
    "saldo_baixo_threshold": 120,
}


def utc(ano, mes, dia, hora=12, minuto=0) -> datetime:
    return datetime(ano, mes, dia, hora, minuto, tzinfo=timezone.utc)


@pytest.fixture
def ambiente(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "public_build", True)
    monkeypatch.setattr(settings, "clipmint_password", "")
    monkeypatch.setattr(settings, "storage_dir", str(tmp_path / "storage"))
    settings.ensure_dirs()

    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'a.db'}")
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
    return TestClient(app), factory


def _entrar(cliente, email, dono=False, factory=None):
    assert (
        cliente.post(
            "/api/auth/register",
            json={"email": email, "password": "uma-senha-bem-longa"},
        ).status_code
        == 201
    )
    if dono:

        async def promover():
            async with factory() as db:
                await db.execute(
                    update(User).where(User.email == email).values(is_owner=True)
                )
                await db.commit()

        asyncio.run(promover())


async def _uid(factory, email) -> str:
    async with factory() as db:
        return await db.scalar(select(User.id).where(User.email == email))


def _pagamento(uid, *, bruto, pago_em, taxa=None, gid=None):
    return Payment(
        user_id=uid,
        gateway_payment_id=gid or f"mp-{pago_em.isoformat()}-{bruto}",
        tipo="topup",
        amount_brl_gross=Decimal(str(bruto)),
        gateway_fee_brl=None if taxa is None else Decimal(str(taxa)),
        credits_granted=300,
        status="paid",
        paid_at=pago_em,
    )


def _uso(uid, *, custo, quando, cobrado=120, status="success"):
    return UsageEvent(
        user_id=uid,
        created_at=quando,
        total_cost_brl=Decimal(str(custo)),
        credits_charged=cobrado,
        status=status,
    )


# ─── A fechadura ──────────────────────────────────────────────────────────────


ROTAS = ["/api/admin/overview", "/api/admin/series", "/api/admin/users", "/api/admin/cost-config"]


@pytest.mark.parametrize("rota", ROTAS)
def test_usuario_comum_leva_403_do_servidor(ambiente, rota):
    """Esconder na interface não é proteção."""
    cliente, factory = ambiente
    _entrar(cliente, "comum@exemplo.com", factory=factory)
    assert cliente.get(rota).status_code == 403


@pytest.mark.parametrize("rota", ROTAS)
def test_sem_sessao_nao_passa(ambiente, rota):
    cliente, _ = ambiente
    assert cliente.get(rota).status_code == 401


@pytest.mark.parametrize("rota", ROTAS)
def test_dono_entra(ambiente, rota):
    cliente, factory = ambiente
    _entrar(cliente, "dono@exemplo.com", dono=True, factory=factory)
    assert cliente.get(rota).status_code == 200


def test_painel_nao_existe_na_versao_pessoal(tmp_path, monkeypatch):
    """Lá não há receita nem cliente para monitorar."""
    monkeypatch.setattr(settings, "public_build", False)
    app = FastAPI()
    register_routers(app)
    assert not [r for r in app.routes if "admin" in getattr(r, "path", "")]


# ─── A fronteira do mês ───────────────────────────────────────────────────────


def test_mes_vai_ate_a_meia_noite_de_sao_paulo(ambiente):
    """31/07 23:00 em São Paulo é 01/08 02:00 em UTC — e é receita de JULHO.

    Este é o teste que separa o painel certo do painel que erra a virada: em UTC,
    as três últimas horas de todo dia 31 caem no mês seguinte.
    """
    cliente, factory = ambiente
    _entrar(cliente, "dono@exemplo.com", dono=True, factory=factory)
    uid = asyncio.run(_uid(factory, "dono@exemplo.com"))

    async def semear():
        async with factory() as db:
            db.add_all(
                [
                    # 31/07 23:00 local
                    _pagamento(uid, bruto=100, pago_em=utc(2026, 8, 1, 2, 0), gid="julho"),
                    # 01/08 00:30 local
                    _pagamento(uid, bruto=200, pago_em=utc(2026, 8, 1, 3, 30), gid="agosto"),
                ]
            )
            await db.commit()

    asyncio.run(semear())

    corpo = cliente.get(f"/api/admin/overview?mes={MES}").json()
    assert Decimal(str(corpo["atual"]["receita_bruta_brl"])) == Decimal("200.00")
    assert Decimal(str(corpo["anterior"]["receita_bruta_brl"])) == Decimal("100.00")


def test_periodo_invalido_e_recusado(ambiente):
    cliente, factory = ambiente
    _entrar(cliente, "dono@exemplo.com", dono=True, factory=factory)
    resp = cliente.get("/api/admin/overview?mes=agosto")
    assert resp.status_code == 422
    assert "AAAA-MM" in resp.json()["detail"]


# ─── A conta ──────────────────────────────────────────────────────────────────


def _cenario(cliente, factory):
    _entrar(cliente, "dono@exemplo.com", dono=True, factory=factory)
    uid = asyncio.run(_uid(factory, "dono@exemplo.com"))

    async def semear():
        async with factory() as db:
            db.add(_pagamento(uid, bruto=1000, pago_em=utc(2026, 8, 10), taxa=10, gid="p1"))
            db.add(_uso(uid, custo="30.00", quando=utc(2026, 8, 11)))
            # Pendente não é receita.
            pendente = _pagamento(uid, bruto=500, pago_em=None, gid="p2")
            pendente.status = "pending"
            db.add(pendente)
            await db.commit()

    asyncio.run(semear())
    return uid


def test_lucro_segue_a_formula(ambiente):
    cliente, factory = ambiente
    _cenario(cliente, factory)

    v = cliente.get(f"/api/admin/overview?mes={MES}").json()["atual"]

    assert Decimal(str(v["receita_bruta_brl"])) == Decimal("1000.00")
    assert Decimal(str(v["taxas_gateway_brl"])) == Decimal("10.00")
    assert Decimal(str(v["custo_variavel_brl"])) == Decimal("30.00")
    assert Decimal(str(v["custo_fixo_brl"])) == Decimal("57.00")
    # 15% de 1000
    assert Decimal(str(v["imposto_brl"])) == Decimal("150.00")
    # 1000 - 30 - 57 - 150 - 10
    assert Decimal(str(v["lucro_liquido_brl"])) == Decimal("753.00")
    assert Decimal(str(v["margem_liquida_pct"])) == Decimal("75.30")
    # O pagamento pendente ficou de fora.
    assert v["pagamentos"] == 1


def test_taxa_nao_informada_e_estimada_e_avisada(ambiente):
    """O gateway só informa a taxa depois de liquidar."""
    cliente, factory = ambiente
    _entrar(cliente, "dono@exemplo.com", dono=True, factory=factory)
    uid = asyncio.run(_uid(factory, "dono@exemplo.com"))

    async def semear():
        async with factory() as db:
            db.add(_pagamento(uid, bruto=1000, pago_em=utc(2026, 8, 10), taxa=None, gid="s1"))
            await db.commit()

    asyncio.run(semear())
    v = cliente.get(f"/api/admin/overview?mes={MES}").json()["atual"]

    # 1% da configuração
    assert Decimal(str(v["taxas_gateway_brl"])) == Decimal("10.00")
    assert v["taxas_estimadas"] == 1
    assert any("sem taxa informada" in a for a in v["avisos"])


def test_prejuizo_por_job_devolvido_aparece_separado(ambiente):
    """A decisão de não cobrar job que falha tem um preço, e ele fica visível."""
    cliente, factory = ambiente
    _entrar(cliente, "dono@exemplo.com", dono=True, factory=factory)
    uid = asyncio.run(_uid(factory, "dono@exemplo.com"))

    async def semear():
        async with factory() as db:
            db.add(_uso(uid, custo="3.23", quando=utc(2026, 8, 5), cobrado=120))
            db.add(
                _uso(uid, custo="2.27", quando=utc(2026, 8, 6), cobrado=0, status="failed")
            )
            db.add(
                _uso(uid, custo="1.13", quando=utc(2026, 8, 7), cobrado=0, status="deleted")
            )
            await db.commit()

    asyncio.run(semear())
    v = cliente.get(f"/api/admin/overview?mes={MES}").json()["atual"]

    assert Decimal(str(v["custo_variavel_brl"])) == Decimal("6.63")
    assert Decimal(str(v["prejuizo_devolvido_brl"])) == Decimal("3.40")
    assert v["videos_devolvidos"] == 2
    assert v["videos_processados"] == 3


def test_mrr_e_churn(ambiente):
    cliente, factory = ambiente
    _entrar(cliente, "dono@exemplo.com", dono=True, factory=factory)
    uid = asyncio.run(_uid(factory, "dono@exemplo.com"))

    async def semear():
        async with factory() as db:
            for n in range(3):
                db.add(
                    Subscription(
                        user_id=uid,
                        plan_code="pro",
                        valor_brl=Decimal("99.90"),
                        creditos_mes=1200,
                        status="active",
                        started_at=utc(2026, 7, 1),
                        gateway_preapproval_id=f"pre-{n}",
                    )
                )
            db.add(
                Subscription(
                    user_id=uid,
                    plan_code="pro",
                    valor_brl=Decimal("99.90"),
                    creditos_mes=1200,
                    status="canceled",
                    started_at=utc(2026, 7, 1),
                    canceled_at=utc(2026, 8, 15),
                    gateway_preapproval_id="pre-x",
                )
            )
            await db.commit()

    asyncio.run(semear())
    v = cliente.get(f"/api/admin/overview?mes={MES}").json()["atual"]

    assert v["assinantes_ativos"] == 3
    assert Decimal(str(v["mrr_brl"])) == Decimal("299.70")
    assert v["cancelados_no_mes"] == 1
    # Base do início do mês: 3 ativos - 0 novos + 1 cancelado = 4. 1/4 = 25%.
    assert Decimal(str(v["churn_pct"])) == Decimal("25.00")


# ─── Série e usuários ─────────────────────────────────────────────────────────


def test_serie_cobre_o_mes_inteiro_com_zeros(ambiente):
    """Gráfico que pula dia vazio comprime o eixo e mente sobre o ritmo."""
    cliente, factory = ambiente
    _cenario(cliente, factory)

    serie = cliente.get(f"/api/admin/series?mes={MES}").json()
    assert len(serie) == 31
    assert serie[0]["dia"] == "2026-08-01"
    assert Decimal(str(serie[0]["receita_brl"])) == Decimal("0.00")

    dia10 = next(d for d in serie if d["dia"] == "2026-08-10")
    assert Decimal(str(dia10["receita_brl"])) == Decimal("1000.00")
    dia11 = next(d for d in serie if d["dia"] == "2026-08-11")
    assert Decimal(str(dia11["custo_brl"])) == Decimal("30.00")
    assert Decimal(str(dia11["lucro_brl"])) == Decimal("-30.00")


def test_tabela_por_usuario_destaca_deficitario(ambiente):
    """É isto que vai embasar a política de rate limit."""
    cliente, factory = ambiente
    _entrar(cliente, "dono@exemplo.com", dono=True, factory=factory)
    _entrar(cliente, "caro@exemplo.com", factory=factory)
    dono = asyncio.run(_uid(factory, "dono@exemplo.com"))
    caro = asyncio.run(_uid(factory, "caro@exemplo.com"))

    async def semear():
        async with factory() as db:
            db.add(_pagamento(dono, bruto=100, pago_em=utc(2026, 8, 3), gid="d1"))
            db.add(_uso(dono, custo="10.00", quando=utc(2026, 8, 3)))
            # Paga pouco e usa muito.
            db.add(_pagamento(caro, bruto=36, pago_em=utc(2026, 8, 4), gid="c1"))
            db.add(_uso(caro, custo="90.00", quando=utc(2026, 8, 4)))
            await db.commit()

    asyncio.run(semear())

    # A sessão atual é a do usuário comum; volta para o dono.
    cliente.post("/api/auth/logout")
    assert (
        cliente.post(
            "/api/auth/login",
            json={"email": "dono@exemplo.com", "password": "uma-senha-bem-longa"},
        ).status_code
        == 200
    )

    linhas = cliente.get(f"/api/admin/users?mes={MES}").json()
    assert len(linhas) == 2
    # O deficitário vem primeiro: quem precisa de decisão aparece antes.
    assert linhas[0]["email"] == "caro@exemplo.com"
    assert linhas[0]["deficitario"] is True
    assert Decimal(str(linhas[0]["resultado_brl"])) == Decimal("-54.00")
    assert linhas[1]["deficitario"] is False


# ─── Configuração de tarifas ──────────────────────────────────────────────────


def test_alterar_tarifa_nao_reescreve_evento(ambiente):
    cliente, factory = ambiente
    _cenario(cliente, factory)

    antes = cliente.get(f"/api/admin/overview?mes={MES}").json()["atual"]
    assert Decimal(str(antes["custo_variavel_brl"])) == Decimal("30.00")

    resp = cliente.put("/api/admin/cost-config", json={"fx_usd_brl": "9.00"})
    assert resp.status_code == 200
    assert Decimal(str(resp.json()["fx_usd_brl"])) == Decimal("9.00")

    depois = cliente.get(f"/api/admin/overview?mes={MES}").json()["atual"]
    # O custo já gravado não se mexe — ele congelou a própria taxa.
    assert Decimal(str(depois["custo_variavel_brl"])) == Decimal("30.00")


def test_alterar_imposto_muda_a_projecao(ambiente):
    """O que a configuração MUDA é o cálculo do mês, não o custo já gravado."""
    cliente, factory = ambiente
    _cenario(cliente, factory)

    cliente.put("/api/admin/cost-config", json={"tax_pct_on_revenue": "6"})
    v = cliente.get(f"/api/admin/overview?mes={MES}").json()["atual"]

    assert Decimal(str(v["imposto_brl"])) == Decimal("60.00")
    assert Decimal(str(v["lucro_liquido_brl"])) == Decimal("843.00")


def test_put_vazio_e_recusado(ambiente):
    cliente, factory = ambiente
    _entrar(cliente, "dono@exemplo.com", dono=True, factory=factory)
    assert cliente.put("/api/admin/cost-config", json={}).status_code == 422


# ─── Quem administra num servidor novo ────────────────────────────────────────


def test_owner_email_promove_a_conta_no_startup(ambiente, monkeypatch):
    """Sem isto, ninguém administra um servidor novo — nem quem o instalou.

    O cadastro público sempre grava `is_owner=False`, e tem que ser assim. A
    coroa vem de `OWNER_EMAIL`, no startup.
    """
    from app.services.auth import promote_owner

    cliente, factory = ambiente
    _entrar(cliente, "chefe@exemplo.com", factory=factory)
    monkeypatch.setattr(settings, "owner_email", "chefe@exemplo.com")

    # Antes: cadastrado, mas sem poder nenhum.
    assert cliente.get("/api/admin/overview").status_code == 403

    async def startup():
        async with factory() as db:
            await promote_owner(db)

    asyncio.run(startup())
    assert cliente.get("/api/admin/overview").status_code == 200


def test_owner_email_sem_conta_nao_cria_usuario(ambiente, monkeypatch):
    """Criar aqui faria um administrador SEM SENHA num servidor exposto."""
    from app.services.auth import promote_owner

    _, factory = ambiente
    monkeypatch.setattr(settings, "owner_email", "ninguem@exemplo.com")

    async def rodar():
        async with factory() as db:
            promovido = await promote_owner(db)
            existe = await db.scalar(
                select(User).where(User.email == "ninguem@exemplo.com")
            )
            return promovido, existe

    promovido, existe = asyncio.run(rodar())
    assert promovido is None
    assert existe is None


def test_promover_e_idempotente(ambiente, monkeypatch):
    from app.services.auth import promote_owner

    cliente, factory = ambiente
    _entrar(cliente, "chefe@exemplo.com", factory=factory)
    monkeypatch.setattr(settings, "owner_email", "chefe@exemplo.com")

    async def rodar():
        async with factory() as db:
            await promote_owner(db)
            await promote_owner(db)
            return len(
                (await db.execute(select(User).where(User.is_owner))).scalars().all()
            )

    assert asyncio.run(rodar()) == 1
