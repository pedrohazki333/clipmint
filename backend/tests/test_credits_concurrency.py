"""
Dois jobs, um saldo: o teste que justifica o desenho.

Este é o ponto onde o sistema pode perder dinheiro de verdade. Sem o
`SELECT ... FOR UPDATE` de services/credits.py, requisições simultâneas leem o
mesmo saldo, cada uma conclui que dá, e todas gravam — o usuário processa vários
vídeos pagando por um. O bug não aparece em teste sequencial nem em uso manual:
aparece em produção, com dois cliques rápidos ou uma aba duplicada.

Precisa de Postgres. O SQLite não tem row lock, e é justamente por isso que o
build público recusa subir nele. Sem banco disponível, o teste é PULADO e diz
por quê — nunca "passa" por ausência.
"""

import asyncio

import pytest
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from tests.conftest import SEM_POSTGRES, postgres_disponivel, postgres_url
from app.models import BillingConfig, CreditLedger, User
from app.services import credits
from app.services.credits import SaldoInsuficiente

#: Quantas requisições disputam o saldo ao mesmo tempo. Oito, e não duas, para
#: que a serialização por acaso não faça o teste passar com o lock quebrado.
CONCORRENTES = 8
CUSTO = 120


#: A checagem de disponibilidade mora no conftest: dois módulos precisam dela, e
#: duas cópias divergiriam no dia em que a forma de achar o banco mudasse.
URL = postgres_url()

pytestmark = pytest.mark.skipif(
    not postgres_disponivel(URL),
    reason=SEM_POSTGRES + " O teste de concorrência não roda em SQLite.",
)


async def _com_saldo(factory, email: str, saldo: int) -> str:
    """Cria um usuário com saldo, pelo caminho normal. Devolve o id."""
    async with factory() as db:
        user = User(email=email, password_hash="x")
        db.add(user)
        await db.flush()
        await credits.lancar(db, user_id=user.id, tipo="topup", amount=saldo)
        await db.commit()
        return user.id


async def _limpar(factory, user_id: str) -> None:
    async with factory() as db:
        await db.execute(delete(CreditLedger).where(CreditLedger.user_id == user_id))
        await db.execute(delete(User).where(User.id == user_id))
        await db.commit()


def test_o_lock_segura_o_segundo_lancamento_ate_o_commit(tmp_path):
    """O teste que realmente prova o lock: intercalamento FORÇADO, não sorteado.

    Disparar N requisições com `asyncio.gather` e torcer pela corrida NÃO serve
    — foi a primeira versão deste teste, e ela passava igual com o
    `with_for_update()` removido: as tarefas serializavam sozinhas e a janela
    perigosa nunca chegava a abrir. Um teste de concorrência que passa com a
    proteção desligada não é teste, é decoração.

    Aqui a janela é aberta à mão:

      1. a sessão A lança e NÃO commita — fica segurando a linha;
      2. a sessão B tenta lançar e tem que FICAR BLOQUEADA (o `wait_for`
         estoura, e é isso que se afirma);
      3. A commita; B destrava, relê o saldo já debitado e é recusada.

    Sem o `FOR UPDATE`, o passo 2 não bloqueia: B lê o saldo antigo na hora,
    conclui que dá, e as duas gravam. O teste falha, que é o que se quer.
    """

    async def principal():
        engine = create_async_engine(URL, pool_size=4)
        factory = async_sessionmaker(
            bind=engine, class_=AsyncSession, expire_on_commit=False
        )
        email = f"lock-{tmp_path.name}@teste.local"
        user_id = await _com_saldo(factory, email, CUSTO)

        try:
            async with factory() as a, factory() as b:
                # 1. A segura a linha e não solta.
                await credits.lancar(
                    db=a, user_id=user_id, tipo="hold", amount=-CUSTO, descricao="A"
                )

                # 2. B tem que ficar esperando. Se voltar antes do prazo, o lock
                #    não existe — e é exatamente esse o modo de falha.
                async def b_tenta():
                    return await credits.lancar(
                        db=b, user_id=user_id, tipo="hold", amount=-CUSTO, descricao="B"
                    )

                tarefa = asyncio.create_task(b_tenta())
                with pytest.raises(asyncio.TimeoutError):
                    await asyncio.wait_for(asyncio.shield(tarefa), timeout=2.0)

                # 3. A solta; B acorda e enxerga o saldo JÁ debitado.
                await a.commit()

                with pytest.raises(SaldoInsuficiente):
                    await asyncio.wait_for(tarefa, timeout=10.0)
                await b.rollback()

            async with factory() as db:
                assert await credits.saldo(db, user_id) == 0
                assert await credits.saldo_do_ledger(db, user_id) == 0
        finally:
            await _limpar(factory, user_id)
            await engine.dispose()

    asyncio.run(principal())


def test_saldo_para_um_job_nao_paga_dois(tmp_path):
    """Oito requisições, saldo para uma — pelo caminho de verdade, sem encenação.

    Complementa o teste acima, não o substitui: aqui o intercalamento fica por
    conta do agendador, e na prática ele costuma serializar. Serve como
    verificação de ponta a ponta (o saldo final fecha, o extrato bate com o
    cache); quem prova o lock é o `wait_for` do teste anterior.
    """

    async def principal():
        engine = create_async_engine(URL, pool_size=CONCORRENTES + 2, max_overflow=2)
        factory = async_sessionmaker(
            bind=engine, class_=AsyncSession, expire_on_commit=False
        )
        email = f"corrida-{tmp_path.name}@teste.local"
        user_id = await _com_saldo(factory, email, CUSTO)

        async def tentar(n: int):
            """Uma requisição: sessão e transação próprias, como no servidor."""
            async with factory() as db:
                try:
                    await credits.lancar(
                        db,
                        user_id=user_id,
                        tipo="hold",
                        amount=-CUSTO,
                        descricao=f"tentativa {n}",
                    )
                    await db.commit()
                    return True
                except SaldoInsuficiente:
                    await db.rollback()
                    return False

        try:
            resultados = await asyncio.gather(
                *(tentar(n) for n in range(CONCORRENTES))
            )

            assert sum(resultados) == 1, (
                f"{sum(resultados)} requisições passaram com saldo para uma — "
                "o lock de linha não está segurando"
            )

            async with factory() as db:
                saldo = await credits.saldo(db, user_id)
                do_ledger = await credits.saldo_do_ledger(db, user_id)

            assert saldo == 0
            # O cache e o extrato não podem divergir nem sob concorrência.
            assert saldo == do_ledger
            assert saldo >= 0
        finally:
            await _limpar(factory, user_id)
            await engine.dispose()

    asyncio.run(principal())


def test_creditar_e_debitar_ao_mesmo_tempo_nao_perde_lancamento(tmp_path):
    """Recarga e consumo concorrentes: nenhum dos dois pode sumir.

    O caso real é o webhook do pagamento chegando enquanto o usuário dispara um
    job. Com leitura-modificação-escrita sem lock, um dos dois sobrescreve o
    outro e o saldo final fica errado para um lado ou para o outro.
    """

    async def principal():
        engine = create_async_engine(URL, pool_size=CONCORRENTES + 2, max_overflow=2)
        factory = async_sessionmaker(
            bind=engine, class_=AsyncSession, expire_on_commit=False
        )
        email = f"misto-{tmp_path.name}@teste.local"
        user_id = await _com_saldo(factory, email, 1000)

        async def lancar(tipo: str, amount: int):
            async with factory() as db:
                await credits.lancar(db, user_id=user_id, tipo=tipo, amount=amount)
                await db.commit()

        try:
            await asyncio.gather(
                *(lancar("topup", 100) for _ in range(4)),
                *(lancar("hold", -50) for _ in range(4)),
            )

            async with factory() as db:
                saldo = await credits.saldo(db, user_id)
                do_ledger = await credits.saldo_do_ledger(db, user_id)
                linhas = await db.scalar(
                    select(CreditLedger.id)
                    .where(CreditLedger.user_id == user_id)
                    .with_only_columns(CreditLedger.id)
                    .limit(1)
                )

            # 1000 + 4x100 - 4x50 = 1200. Nenhum lançamento pode ter se perdido.
            assert saldo == 1200
            assert do_ledger == 1200
            assert linhas is not None
        finally:
            await _limpar(factory, user_id)
            await engine.dispose()

    asyncio.run(principal())


# ─── Duas notificações do mesmo pagamento, ao mesmo tempo ─────────────────────


def test_webhook_simultaneo_credita_uma_vez_so(tmp_path, monkeypatch):
    """Duas notificações do MESMO pagamento, com o intercalamento forçado.

    O caso sequencial (o MP reenviando depois) já é barrado pelo retorno
    antecipado de `sincronizar`. Este é o outro, e é o perigoso: as duas leem
    `pending` antes de qualquer uma gravar.

    Como no teste do lock acima, `asyncio.gather` NÃO serve — verificado: com o
    UPDATE condicional trocado por um `if` em Python, a versão com `gather`
    continuava passando, porque as tarefas serializavam sozinhas. Aqui a janela
    é aberta à mão: A faz a transição e segura a transação; B tenta e tem que
    BLOQUEAR; A commita; B destrava e volta com `False`, sem creditar.
    """
    from decimal import Decimal

    from app.models import Payment
    from app.services import payments

    async def principal():
        engine = create_async_engine(URL, pool_size=6)
        factory = async_sessionmaker(
            bind=engine, class_=AsyncSession, expire_on_commit=False
        )
        email = f"webhook-{tmp_path.name}@teste.local"

        async with factory() as db:
            user = User(email=email, password_hash="x")
            db.add(user)
            await db.flush()
            pagamento = Payment(
                user_id=user.id,
                gateway_payment_id=f"MP-{tmp_path.name}",
                tipo="topup",
                amount_brl_gross=Decimal("30.00"),
                credits_granted=300,
                status="pending",
            )
            db.add(pagamento)
            await db.commit()
            user_id, pagamento_id = user.id, pagamento.id

        try:
            async with factory() as a, factory() as b:
                pag_a = await a.get(Payment, pagamento_id)
                pag_b = await b.get(Payment, pagamento_id)
                # As duas enxergam "pending": é exatamente a situação de risco.
                assert pag_a.status == "pending" and pag_b.status == "pending"

                creditou_a = await payments._marcar_pago_e_creditar(a, pag_a, {})
                assert creditou_a is True

                tarefa = asyncio.create_task(
                    payments._marcar_pago_e_creditar(b, pag_b, {})
                )
                with pytest.raises(asyncio.TimeoutError):
                    await asyncio.wait_for(asyncio.shield(tarefa), timeout=2.0)

                await a.commit()

                creditou_b = await asyncio.wait_for(tarefa, timeout=10.0)
                assert creditou_b is False, "os dois creditaram — pagou uma, recebeu duas"
                await b.commit()

            async with factory() as db:
                saldo = await credits.saldo(db, user_id)
                do_ledger = await credits.saldo_do_ledger(db, user_id)

            assert saldo == 300, f"creditou {saldo} em vez de 300"
            assert do_ledger == 300
        finally:
            async with factory() as db:
                await db.execute(
                    delete(CreditLedger).where(CreditLedger.user_id == user_id)
                )
                await db.execute(delete(Payment).where(Payment.id == pagamento_id))
                await db.execute(delete(User).where(User.id == user_id))
                await db.commit()
            await engine.dispose()

    asyncio.run(principal())
