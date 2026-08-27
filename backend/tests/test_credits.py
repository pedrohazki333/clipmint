"""
Saldo de créditos: as invariantes que não podem quebrar.

O que estes testes guardam não é "a função soma certo" — é que o dinheiro do
usuário e o extrato nunca se separem, e que nada seja cobrado ou creditado duas
vezes. As três garantias de "uma vez só" moram em índices do BANCO, e é assim
que são testadas: tentando gravar a segunda linha e exigindo que o banco recuse.

A concorrência de verdade (dois jobs disputando o mesmo saldo) precisa de
Postgres e está em test_credits_concurrency.py — o SQLite destes testes não tem
`SELECT ... FOR UPDATE`.
"""

import asyncio
from decimal import Decimal

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.database import Base
from app.models import BillingConfig, CreditLedger, Job, Payment, User
from app.services import billing, credits
from app.services.credits import SaldoInsuficiente

#: Valores explícitos, e não os padrões de produção: um teste que depende do
#: preço configurado passa a falhar quando o dono muda o preço, que é
#: exatamente o que ele não deveria fazer.
CONFIG_TESTE = {
    "id": 1,
    "credito_avulso_brl": Decimal("0.10"),
    "pacotes": [
        {"creditos": 300, "preco_brl": None},
        {"creditos": 1500, "preco_brl": "120.00"},
    ],
    "planos": [],
    "creditos_gratis_cadastro": 30,
    "saldo_baixo_threshold": 120,
}


@pytest.fixture
def factory(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'c.db'}")
    fabrica = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)

    async def montar():
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        async with fabrica() as s:
            s.add(BillingConfig(**CONFIG_TESTE))
            await s.commit()

    asyncio.run(montar())
    return fabrica


async def _usuario(db: AsyncSession, email="a@b.c") -> User:
    user = User(email=email, password_hash="x")
    db.add(user)
    await db.flush()
    return user


def rodar(factory, corpo):
    """Executa uma corrotina que recebe uma sessão."""

    async def principal():
        async with factory() as db:
            return await corpo(db)

    return asyncio.run(principal())


# ─── O saldo e o extrato andam juntos ─────────────────────────────────────────


def test_conta_nova_comeca_zerada(factory):
    async def corpo(db):
        user = await _usuario(db)
        assert await credits.saldo(db, user.id) == 0

    rodar(factory, corpo)


def test_lancamento_atualiza_cache_extrato_e_balance_after(factory):
    async def corpo(db):
        user = await _usuario(db)
        await credits.lancar(db, user_id=user.id, tipo="topup", amount=300)
        await credits.lancar(db, user_id=user.id, tipo="hold", amount=-120)
        await db.commit()

        assert await credits.saldo(db, user.id) == 180
        # A invariante central: o cache e a soma do extrato NUNCA divergem.
        assert await credits.saldo_do_ledger(db, user.id) == 180

        extrato = (
            await db.execute(
                CreditLedger.__table__.select().order_by(CreditLedger.created_at)
            )
        ).fetchall()
        assert [l.amount for l in extrato] == [300, -120]
        assert [l.balance_after for l in extrato] == [300, 180]

    rodar(factory, corpo)


def test_debito_sem_saldo_e_recusado_sem_escrever_nada(factory):
    async def corpo(db):
        user = await _usuario(db)
        await credits.lancar(db, user_id=user.id, tipo="topup", amount=50)
        await db.commit()

        with pytest.raises(SaldoInsuficiente) as erro:
            await credits.lancar(db, user_id=user.id, tipo="debito", amount=-120)

        # 402, e não 403: é falta de saldo, e a interface usa isso para mandar
        # o usuário à recarga em vez de dizer "acesso negado".
        assert erro.value.status_code == 402
        assert erro.value.necessario == 120
        assert erro.value.disponivel == 50
        assert await credits.saldo(db, user.id) == 50
        assert await credits.saldo_do_ledger(db, user.id) == 50

    rodar(factory, corpo)


def test_ajuste_de_admin_pode_deixar_negativo(factory):
    """Um estorno de chargeback pode legitimamente derrubar a conta abaixo de zero."""

    async def corpo(db):
        user = await _usuario(db)
        await credits.lancar(db, user_id=user.id, tipo="topup", amount=100)
        await credits.lancar(
            db,
            user_id=user.id,
            tipo="ajuste",
            amount=-150,
            permitir_negativo=True,
            descricao="estorno de chargeback",
        )
        await db.commit()

        assert await credits.saldo(db, user.id) == -50
        assert await credits.saldo_do_ledger(db, user.id) == -50

    rodar(factory, corpo)


def test_hold_ja_desconta_do_saldo(factory):
    """É o hold que impede disparar dez jobs com crédito para um."""

    async def corpo(db):
        user = await _usuario(db)
        await credits.lancar(db, user_id=user.id, tipo="topup", amount=120)
        job = Job(id="j1", youtube_url="u", status="queued", user_id=user.id)
        db.add(job)
        await db.flush()

        await credits.lancar(
            db, user_id=user.id, tipo="hold", amount=-120, ref_usage_id=job.id
        )
        await db.commit()

        assert await credits.saldo(db, user.id) == 0
        # Um segundo job do mesmo tamanho não passa: o saldo já está segurado.
        with pytest.raises(SaldoInsuficiente):
            await credits.lancar(db, user_id=user.id, tipo="hold", amount=-120)

    rodar(factory, corpo)


@pytest.mark.parametrize(
    "kwargs",
    [
        {"tipo": "inexistente", "amount": 10},
        {"tipo": "topup", "amount": 0},
    ],
)
def test_lancamento_invalido_e_recusado(factory, kwargs):
    async def corpo(db):
        user = await _usuario(db)
        with pytest.raises(ValueError):
            await credits.lancar(db, user_id=user.id, **kwargs)

    rodar(factory, corpo)


# ─── "Uma vez só", garantido pelo banco ───────────────────────────────────────


def test_um_pagamento_credita_uma_vez_so(factory):
    """O webhook do Mercado Pago reenvia notificação. O índice é quem barra."""

    async def corpo(db):
        user = await _usuario(db)
        pag = Payment(
            user_id=user.id,
            gateway_payment_id="mp-123",
            tipo="topup",
            amount_brl_gross=Decimal("30.00"),
            credits_granted=300,
            status="paid",
        )
        db.add(pag)
        await db.flush()

        await credits.lancar(
            db, user_id=user.id, tipo="topup", amount=300, ref_payment_id=pag.id
        )
        await db.commit()

        with pytest.raises(IntegrityError):
            await credits.lancar(
                db, user_id=user.id, tipo="topup", amount=300, ref_payment_id=pag.id
            )
            await db.commit()

    rodar(factory, corpo)


def test_o_mesmo_pagamento_do_gateway_nao_vira_duas_linhas(factory):
    async def corpo(db):
        user = await _usuario(db)
        for _ in range(2):
            db.add(
                Payment(
                    user_id=user.id,
                    gateway_payment_id="mp-999",
                    tipo="topup",
                    amount_brl_gross=Decimal("30.00"),
                    credits_granted=300,
                    status="pending",
                )
            )
        with pytest.raises(IntegrityError):
            await db.commit()

    rodar(factory, corpo)


def test_um_job_segura_e_cobra_uma_vez_so(factory):
    """Este projeto retoma job à mão depois de reinício. Retomar não pode cobrar de novo."""

    async def corpo(db):
        user = await _usuario(db)
        await credits.lancar(db, user_id=user.id, tipo="topup", amount=1000)
        job = Job(id="j-retomado", youtube_url="u", status="queued", user_id=user.id)
        db.add(job)
        await db.flush()
        await credits.lancar(
            db, user_id=user.id, tipo="hold", amount=-120, ref_usage_id=job.id
        )
        await db.commit()

        with pytest.raises(IntegrityError):
            await credits.lancar(
                db, user_id=user.id, tipo="hold", amount=-120, ref_usage_id=job.id
            )
            await db.commit()

    rodar(factory, corpo)


# ─── Bônus de cadastro ────────────────────────────────────────────────────────


def test_bonus_de_cadastro_credita_o_configurado(factory):
    async def corpo(db):
        user = await _usuario(db)
        lanc = await credits.conceder_bonus_cadastro(db, user)
        await db.commit()

        assert lanc is not None
        assert lanc.tipo == "bonus"
        assert await credits.saldo(db, user.id) == 30

    rodar(factory, corpo)


def test_trial_desligado_nao_concede_nada(factory):
    async def corpo(db):
        await billing.update_config(db, creditos_gratis_cadastro=0)
        user = await _usuario(db)
        assert await credits.conceder_bonus_cadastro(db, user) is None
        await db.commit()
        assert await credits.saldo(db, user.id) == 0

    rodar(factory, corpo)


# ─── Preço vem da configuração, nunca do código ───────────────────────────────


def test_preco_deriva_do_credito_avulso(factory):
    async def corpo(db):
        config = await billing.get_config(db)
        assert billing.preco_do_pacote(config, 300) == Decimal("30.00")

    rodar(factory, corpo)


def test_pacote_com_preco_proprio_ganha_desconto(factory):
    async def corpo(db):
        config = await billing.get_config(db)
        # 1500 x 0,10 seriam R$ 150,00; a configuração diz 120,00.
        assert billing.preco_do_pacote(config, 1500) == Decimal("120.00")

    rodar(factory, corpo)


def test_preco_arredonda_para_cima_no_meio_centavo(factory):
    """ROUND_HALF_UP: o padrão do Python é banqueiro e faria 0,125 virar 0,12."""

    async def corpo(db):
        config = await billing.update_config(db, credito_avulso_brl=Decimal("0.125"))
        assert billing.preco_do_pacote(config, 1) == Decimal("0.13")

    rodar(factory, corpo)


def test_alterar_campo_desconhecido_e_recusado(factory):
    async def corpo(db):
        with pytest.raises(ValueError):
            await billing.update_config(db, preco_secreto=1)

    rodar(factory, corpo)


# ─── A migração ───────────────────────────────────────────────────────────────


def test_migracao_cria_o_schema_e_semeia_a_configuracao(tmp_path, monkeypatch):
    """O banco de produção nasce da migração, não do create_all dos testes."""
    from sqlalchemy import create_engine, inspect, text

    from app import db_migrations

    destino = tmp_path / "mig.db"
    engine = create_async_engine(f"sqlite+aiosqlite:///{destino}")
    monkeypatch.setattr(db_migrations, "engine", engine)
    asyncio.run(db_migrations.upgrade_to_head())
    asyncio.run(engine.dispose())

    sinc = create_engine(f"sqlite:///{destino}")
    with sinc.connect() as conn:
        tabelas = set(inspect(conn).get_table_names())
        assert {"credit_ledger", "payments", "subscriptions", "billing_config"} <= tabelas

        linha = conn.execute(
            text(
                "select id, credito_avulso_brl, creditos_gratis_cadastro "
                "from billing_config"
            )
        ).fetchall()
        # Linha única, com os padrões que a migração semeia.
        assert len(linha) == 1
        assert linha[0][0] == 1
        assert float(linha[0][1]) == 0.12
        # 120 depois da 0009 — o trial cabe um vídeo médio inteiro.
        assert linha[0][2] == 120

        # Quem já tinha conta não ganha crédito por efeito de deploy.
        colunas = {c["name"] for c in inspect(conn).get_columns("users")}
        assert "credit_balance" in colunas
    sinc.dispose()


def test_o_banco_migrado_e_o_do_codigo_nascem_iguais(tmp_path, monkeypatch):
    """As duas origens de um banco novo têm que dar na mesma configuração.

    Um banco de produção nasce das MIGRAÇÕES; um banco de teste nasce do
    `create_all` mais o `CONFIG_PADRAO` do serviço. Se os dois divergirem, o
    preço passa a depender de por qual caminho o banco veio — e o teste que
    encontraria isso é este.

    A comparação é contra o ESTADO FINAL da cadeia, e não contra a literal da
    0006. É o que faz uma migração de valor (como a 0009, que sobe o trial)
    continuar sendo verificada em vez de quebrar o teste: o que importa é onde a
    cadeia CHEGA, não o que a primeira migração escreveu.
    """
    from sqlalchemy import create_engine, select

    from app import db_migrations
    from app.models import BillingConfig

    destino = tmp_path / "final.db"
    engine = create_async_engine(f"sqlite+aiosqlite:///{destino}")
    monkeypatch.setattr(db_migrations, "engine", engine)
    asyncio.run(db_migrations.upgrade_to_head())
    asyncio.run(engine.dispose())

    sinc = create_engine(f"sqlite:///{destino}")
    try:
        with sinc.connect() as conn:
            linha = conn.execute(select(BillingConfig)).mappings().one()
    finally:
        sinc.dispose()

    padrao = billing.CONFIG_PADRAO
    assert float(linha["credito_avulso_brl"]) == float(padrao["credito_avulso_brl"])
    assert linha["pacotes"] == padrao["pacotes"]
    assert linha["planos"] == padrao["planos"]
    assert linha["creditos_gratis_cadastro"] == padrao["creditos_gratis_cadastro"]
    assert linha["saldo_baixo_threshold"] == padrao["saldo_baixo_threshold"]
