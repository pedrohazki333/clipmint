"""
Saldo de créditos: o único lugar que escreve no extrato.

A unidade é o CRÉDITO — 1 crédito = 1 minuto de vídeo de origem, sempre inteiro.

O desenho tem duas metades que não podem se separar:

  - `credit_ledger` é append-only e é a **fonte da verdade**;
  - `users.credit_balance` é **cache**, atualizado na MESMA transação.

Nada fora deste módulo escreve em nenhum dos dois. Não é preciosismo de
organização: é aqui que fica o `SELECT ... FOR UPDATE` que serializa lançamentos
concorrentes, e um caminho de escrita que não passe por ele é um caminho por
onde dois jobs simultâneos gastam o mesmo saldo.

**Transação:** as funções daqui dão `flush`, nunca `commit`. Quem chamou decide
o limite da transação — é o que permite conceder o bônus de cadastro na mesma
transação que cria o usuário, ou creditar um pagamento junto da atualização do
`payments.status`, sem janela entre uma coisa e outra.
"""

import logging

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import TIPOS_LANCAMENTO, CreditLedger, User

logger = logging.getLogger(__name__)


class SaldoInsuficiente(HTTPException):
    """402: a conta não tem crédito para o que foi pedido.

    402 e não 403: não é falta de permissão, é falta de saldo, e a interface usa
    exatamente essa diferença para mandar o usuário à tela de recarga em vez de
    mostrar "acesso negado".
    """

    def __init__(self, *, necessario: int, disponivel: int) -> None:
        self.necessario = necessario
        self.disponivel = disponivel
        super().__init__(
            status_code=status.HTTP_402_PAYMENT_REQUIRED,
            detail=(
                f"Saldo insuficiente: são necessários {necessario} créditos e "
                f"você tem {disponivel}."
            ),
        )


async def saldo(db: AsyncSession, user_id: str) -> int:
    """O saldo atual, do cache. Zero se o usuário não existe."""
    valor = await db.scalar(select(User.credit_balance).where(User.id == user_id))
    return int(valor or 0)


async def saldo_do_ledger(db: AsyncSession, user_id: str) -> int:
    """O saldo recomputado somando o extrato inteiro.

    Não é o caminho normal de leitura — é caro e cresce com o histórico. Existe
    para a conferência de invariante (o teste, e uma eventual auditoria): este
    número e o `users.credit_balance` têm que ser sempre iguais.
    """
    total = await db.scalar(
        select(func.coalesce(func.sum(CreditLedger.amount), 0)).where(
            CreditLedger.user_id == user_id
        )
    )
    return int(total or 0)


async def lancar(
    db: AsyncSession,
    *,
    user_id: str,
    tipo: str,
    amount: int,
    ref_payment_id: str | None = None,
    ref_usage_id: str | None = None,
    descricao: str | None = None,
    permitir_negativo: bool = False,
) -> CreditLedger:
    """Grava UM lançamento e atualiza o saldo, atomicamente.

    `amount` vem com sinal: positivo credita, negativo debita. `hold` é negativo
    e `release` é positivo — o saldo já desconta o que está segurado, que é o
    que impede disparar dez jobs com crédito para um.

    O `FOR UPDATE` é o coração da função. Sem ele, duas requisições simultâneas
    leem o mesmo saldo, cada uma conclui que dá, e as duas gravam: o usuário
    processa dois vídeos pagando por um. Com ele, a segunda espera a primeira
    terminar e enxerga o saldo já debitado.

    `permitir_negativo` existe só para `ajuste` de administrador (corrigir um
    estorno de chargeback pode legitimamente deixar a conta negativa). Qualquer
    outro tipo que levaria o saldo abaixo de zero é recusado.
    """
    if tipo not in TIPOS_LANCAMENTO:
        raise ValueError(f"tipo de lançamento desconhecido: {tipo!r}")
    if amount == 0:
        raise ValueError("lançamento de zero crédito não é lançamento")

    # `populate_existing` não é detalhe: sem ele, se o usuário já estiver na
    # sessão (o caso comum — veio da dependência de autenticação), o SELECT
    # trava a linha no banco mas devolve o objeto em memória com o saldo ANTIGO,
    # e o lock deixa de proteger o que deveria. O bug seria invisível em teste
    # sequencial e apareceria só sob concorrência, cobrando errado.
    resultado = await db.execute(
        select(User).where(User.id == user_id).with_for_update().execution_options(
            populate_existing=True
        )
    )
    user = resultado.scalar_one_or_none()
    if user is None:
        raise ValueError(f"usuário inexistente: {user_id!r}")

    anterior = int(user.credit_balance or 0)
    novo = anterior + amount

    if novo < 0 and not permitir_negativo:
        raise SaldoInsuficiente(necessario=abs(amount), disponivel=anterior)

    lancamento = CreditLedger(
        user_id=user_id,
        tipo=tipo,
        amount=amount,
        balance_after=novo,
        ref_payment_id=ref_payment_id,
        ref_usage_id=ref_usage_id,
        descricao=descricao,
    )
    db.add(lancamento)
    user.credit_balance = novo
    await db.flush()

    logger.info(
        "credito: %s %+d para %s (saldo %d -> %d)", tipo, amount, user_id, anterior, novo
    )
    return lancamento


async def conceder_bonus_cadastro(db: AsyncSession, user: User) -> CreditLedger | None:
    """Crédito de boas-vindas, no cadastro. `None` se o trial estiver desligado.

    Chame DENTRO da mesma transação que cria o usuário — é daí que vem a
    garantia de conceder uma vez só. Se a transação for repetida, o INSERT do
    usuário falha no e-mail único e o bônus vai junto no rollback; não existe
    janela em que a conta exista sem o bônus ou com dois.
    """
    from app.services import billing

    config = await billing.get_config(db)
    creditos = int(config.creditos_gratis_cadastro or 0)
    if creditos <= 0:
        return None

    return await lancar(
        db,
        user_id=user.id,
        tipo="bonus",
        amount=creditos,
        descricao="Crédito de boas-vindas",
    )
