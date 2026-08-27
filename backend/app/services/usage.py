"""
Quanto um job custa, e como isso vira lançamento no extrato.

A unidade: **1 crédito = 1 minuto de vídeo de origem**, arredondado para cima.

O ciclo de vida de um job pago tem três lançamentos, e nenhum deles é opcional:

    hold     -E   ao criar o job, com E = estimativa pela consulta de metadados
    release  +E   ao terminar (de qualquer jeito), devolvendo a reserva inteira
    debito   -R   com R = custo real, só quando o job deu certo

O `hold` sai do saldo NA HORA, e é isso que impede disparar dez jobs com saldo
para um: o segundo já não encontra crédito. O `release` devolve a reserva e o
`debito` cobra o que de fato se gastou — em lançamentos separados, para o
extrato do usuário mostrar o que aconteceu em vez de um número líquido que não
explica nada.

**A ordem entre release e debito importa**, e não é estética. Com saldo B e
reserva E, o saldo durante o job é `B - E`. Debitar antes de devolver tentaria
`B - E - R`, que fica negativo sempre que a reserva consumiu quase tudo — e o
lançamento seria RECUSADO por saldo insuficiente, num job que já rodou. Devolver
primeiro leva a `B`, e o débito de `R` cai em cima disso.

Cada um dos três tem índice único parcial por job no banco (migrações 0006 e
0007): segura uma vez, devolve uma vez, cobra uma vez. Um job retomado à mão —
que este projeto faz — não paga de novo.
"""

import logging
import math

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import CreditLedger
from app.services import credits

logger = logging.getLogger(__name__)

#: O job falhou: cobra-se alguma coisa?
#:
#: Não. O usuário não recebeu clip nenhum, e cobrar por trabalho que não
#: entregou é o caminho mais curto para pedido de estorno. O que se perde é o
#: que já foi pago de transcrição num job que quebrou depois dela — um custo
#: real, mas nosso, e do tamanho de um bug nosso.
#:
#: Está aqui, numa constante só, porque é decisão de negócio e pode mudar sem
#: que nada em volta precise mudar junto.
COBRAR_JOB_QUE_FALHOU = False


def custo_em_creditos(segundos: float) -> int:
    """Minutos de vídeo, arredondados para cima. Nunca menos de 1.

    Para cima porque a fatura de transcrição também é: 61 segundos de áudio não
    custam "um minuto e pouco" a ninguém. O mínimo de 1 evita que um vídeo de 20
    segundos saia de graça.
    """
    if segundos <= 0:
        return 0
    return max(1, math.ceil(segundos / 60.0))


async def _lancamento(db: AsyncSession, job_id: str, tipo: str) -> CreditLedger | None:
    return await db.scalar(
        select(CreditLedger).where(
            CreditLedger.ref_usage_id == job_id, CreditLedger.tipo == tipo
        )
    )


async def segurar(
    db: AsyncSession, *, user_id: str, job_id: str, segundos: float
) -> int:
    """Reserva o custo estimado do job. Devolve quantos créditos foram segurados.

    Levanta `SaldoInsuficiente` (402) quando não há saldo — e é esse 402 que a
    interface usa para mandar o usuário à tela de recarga. Chamado na MESMA
    transação que cria o job: sem saldo, o job não chega a existir.
    """
    custo = custo_em_creditos(segundos)
    if custo <= 0:
        # Não deveria acontecer no build público: a guarda de duração recusa
        # vídeo de duração desconhecida antes daqui. Se acontecer, é falha
        # nossa de medição, e a saída é recusar — não processar de graça.
        raise ValueError(
            f"duração desconhecida para o job {job_id}: não dá para reservar crédito"
        )

    await credits.lancar(
        db,
        user_id=user_id,
        tipo="hold",
        amount=-custo,
        ref_usage_id=job_id,
        descricao=f"Reserva do job {job_id} (~{custo} min)",
    )
    return custo


async def reconciliar(
    db: AsyncSession, *, job_id: str, segundos_reais: float | None, sucesso: bool
) -> None:
    """Fecha a conta do job: devolve a reserva e cobra o que se gastou.

    Silenciosa e sem efeito quando não há reserva — job criado antes desta
    fatia, ou versão pessoal, onde não se cobra de ninguém. É o que permite
    chamá-la em todo ponto terminal do pipeline sem condicional em volta.
    """
    hold = await _lancamento(db, job_id, "hold")
    if hold is None:
        return
    if await _lancamento(db, job_id, "release") is not None:
        logger.debug("Job %s já reconciliado; nada a fazer", job_id)
        return

    reservado = -int(hold.amount)

    # 1. Devolver ANTES de cobrar (ver o docstring do módulo).
    await credits.lancar(
        db,
        user_id=hold.user_id,
        tipo="release",
        amount=reservado,
        ref_usage_id=job_id,
        descricao=f"Devolução da reserva do job {job_id}",
    )

    if not sucesso and not COBRAR_JOB_QUE_FALHOU:
        logger.info(
            "Job %s falhou: %s créditos devolvidos, nada cobrado", job_id, reservado
        )
        return

    real = custo_em_creditos(segundos_reais or 0)
    if real <= 0:
        # Job concluído sem duração registrada: cobra-se o que foi reservado, que
        # é o número que o usuário viu e aprovou. Inventar zero seria dar de
        # graça um trabalho que rodou.
        logger.warning(
            "Job %s terminou sem duração conhecida; cobrando a reserva (%s)",
            job_id,
            reservado,
        )
        real = reservado
    elif real > reservado:
        # O vídeo era maior do que a consulta de metadados disse. O erro foi da
        # nossa medição, e quem viu "~E créditos" na tela foi o usuário: cobrar
        # mais do que foi reservado seria cobrança surpresa. Fica registrado
        # para a diferença ser investigada, não repassada.
        logger.warning(
            "Job %s custou %s créditos mas só %s foram reservados — cobrando o "
            "reservado. Estimativa de duração errou para menos.",
            job_id,
            real,
            reservado,
        )
        real = reservado

    await credits.lancar(
        db,
        user_id=hold.user_id,
        tipo="debito",
        amount=-real,
        ref_usage_id=job_id,
        descricao=f"Processamento do job {job_id} ({real} min)",
    )
    logger.info(
        "Job %s reconciliado: reservado %s, cobrado %s", job_id, reservado, real
    )


async def reconciliar_job(job_id: str, *, sucesso: bool) -> None:
    """`reconciliar` com sessão própria, para o pipeline chamar em uma linha.

    A duração real vem de `jobs.duration_seconds`, lida aqui — e não passada
    pelo chamador. O pipeline grava essa coluna com a duração da mídia BAIXADA
    depois do download, substituindo a estimativa da consulta de metadados: é o
    número mais fiel do que foi transcrito, e buscá-lo aqui evita que cada ponto
    terminal tenha que carregar a variável certa até o fim.

    **Nunca deixa uma falha de cobrança derrubar o job.** O status do job é o
    que o usuário vê, e já foi decidido quando isto roda; um erro aqui vira log,
    não exceção. Saldo por conciliar é recuperável — job marcado como erro por
    causa da contabilidade não é.
    """
    from app.database import AsyncSessionLocal
    from app.models import Job

    try:
        async with AsyncSessionLocal() as db:
            segundos = await db.scalar(
                select(Job.duration_seconds).where(Job.id == job_id)
            )
            await reconciliar(
                db, job_id=job_id, segundos_reais=segundos, sucesso=sucesso
            )
            await db.commit()
    except Exception:  # noqa: BLE001 - contabilidade não derruba pipeline
        logger.exception(
            "Falha ao reconciliar créditos do job %s — a reserva continua de pé "
            "e precisa ser resolvida à mão",
            job_id,
        )
