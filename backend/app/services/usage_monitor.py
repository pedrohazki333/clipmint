"""
Gravar o que cada vídeo custou a nós.

Este módulo é a INSTRUMENTAÇÃO: ele observa o pipeline e escreve em
`usage_events`. Nada aqui influencia o processamento, e essa é a propriedade
que ele precisa manter acima de tudo — **nenhuma função daqui pode derrubar um
job**. Todas engolem exceção e registram; medição perdida é recuperável, vídeo
perdido por causa da medição não é.

## Dois momentos, uma linha

`registrar_analise()` roda quando a análise volta, que é o único instante em que
os tokens existem. `fechar()` roda no fim, quando já se sabe como o job terminou
e quanto o usuário foi cobrado. Os dois escrevem na MESMA linha, identificada
pelo `job_id` (índice único).

Isso é de propósito: se o processo morrer entre um e outro, sobra um evento com
os tokens e sem fechamento — que é a verdade ("pagamos a análise e não sabemos
como terminou"), e não um silêncio.

## Custo parcial é a regra, não a exceção

Um job pode morrer no download (não custou nada), depois da transcrição (custou
os minutos), ou depois da análise (custou os dois). Cobrar tudo sempre inflaria
o custo; cobrar zero sempre o esconderia. O que decide é EVIDÊNCIA no banco:

  - transcrição paga = existe linha em `transcripts` para este job;
  - análise paga = os tokens foram registrados;
  - storage = só se houve transcrição (implica que a mídia foi baixada).

`jobs.duration_seconds` sozinho não serve de prova: ele é preenchido na CRIAÇÃO
do job, pela consulta de metadados, e existe mesmo num job que morreu antes de
baixar qualquer coisa.
"""

import logging
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import CreditLedger, Job, Transcript, UsageEvent
from app.services import costs

logger = logging.getLogger(__name__)


async def _evento_do_job(db: AsyncSession, job_id: str) -> UsageEvent:
    """A linha deste job, criando-a se ainda não existir.

    O índice único parcial em `job_id` resolve a corrida: duas gravações
    simultâneas tentam inserir, uma ganha, a outra leva IntegrityError e relê. O
    savepoint permite tratar isso sem envenenar a transação no Postgres.
    """
    existente = await db.scalar(
        select(UsageEvent).where(UsageEvent.job_id == job_id)
    )
    if existente is not None:
        return existente

    novo = UsageEvent(job_id=job_id, status="success")
    try:
        async with db.begin_nested():
            db.add(novo)
        return novo
    except IntegrityError:
        achado = await db.scalar(select(UsageEvent).where(UsageEvent.job_id == job_id))
        if achado is None:
            raise
        return achado


async def registrar_analise(
    db: AsyncSession, job_id: str, *, model: str, input_tokens: int, output_tokens: int
) -> UsageEvent:
    """Guarda os tokens da análise, no instante em que eles existem.

    A API devolve `usage` na resposta e esse número não volta depois: sem
    registrá-lo aqui, o custo de análise viraria estimativa por contagem de
    caracteres — que é exatamente o que este monitor não quer ser.

    Não commita: quem chamou fecha a transação. Mesmo contrato de
    `credits.lancar` e `usage.reconciliar`.
    """
    evento = await _evento_do_job(db, job_id)
    evento.analysis_model = model
    evento.input_tokens = int(input_tokens or 0)
    evento.output_tokens = int(output_tokens or 0)
    await db.flush()
    return evento


async def registrar_analise_job(
    job_id: str, *, model: str, input_tokens: int, output_tokens: int
) -> None:
    """`registrar_analise` com sessão própria, para o analyzer chamar em uma linha."""
    from app.database import AsyncSessionLocal

    try:
        async with AsyncSessionLocal() as db:
            await registrar_analise(
                db,
                job_id,
                model=model,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
            )
            await db.commit()
    except Exception:  # noqa: BLE001 - medição não derruba pipeline
        logger.exception(
            "Falha ao registrar os tokens da análise do job %s — o custo de "
            "análise deste vídeo vai ficar zerado no monitor",
            job_id,
        )


async def _creditos_cobrados(db: AsyncSession, job_id: str) -> int:
    """Quanto o usuário PAGOU por este job, em créditos. 0 quando devolvido."""
    debito = await db.scalar(
        select(CreditLedger.amount).where(
            CreditLedger.ref_usage_id == job_id, CreditLedger.tipo == "debito"
        )
    )
    return -int(debito) if debito else 0


def _promove(status_atual: str | None, status_novo: str) -> bool:
    """Este fechamento corrige um evento que ficou com o resultado errado?

    Um job RETOMADO fecha duas vezes: a tentativa que falhou grava
    `status=failed` com o custo do que já havia sido pago, e o Retomar que
    entrega precisa corrigir a linha. Sem isso o painel mostra como prejuízo um
    vídeo que foi entregue E cobrado — foi o que aconteceu em 01/09/2026, com o
    evento parado em `failed`/`credits_charged=0` enquanto o extrato registrava
    o débito de 81 créditos.

    Só o sentido "não deu certo" → "deu certo" reabre. O contrário nunca: um
    evento de sucesso não pode ser rebaixado por um fechamento tardio.

    **Reabrir não recontabiliza.** O custo é recalculado do zero em `fechar`, a
    partir dos minutos de transcrição e dos tokens que `registrar_analise`
    guardou — e ela sobrescreve, não soma. O total que sai é o do vídeo, não a
    soma das tentativas.
    """
    return status_novo == "success" and status_atual != "success"


async def fechar(db: AsyncSession, job_id: str, *, status: str) -> UsageEvent | None:
    """Calcula o custo final do vídeo e fecha o evento. Não commita.

    Chamar DEPOIS da reconciliação de créditos: é dela que sai o quanto o
    usuário efetivamente pagou, e é o par (custo, cobrado) que diz se este vídeo
    deu prejuízo.

    Não reabre evento já fechado. `rate_snapshot` preenchido é a marca de
    fechado — só esta função escreve snapshot, então ela distingue "linha criada
    pela análise" de "linha já finalizada" sem precisar de coluna nova.

    A exceção é o job RETOMADO: ele fecha duas vezes, e só a segunda sabe o
    resultado. Ver `_promove` abaixo.
    """
    from app.config import settings

    job = await db.scalar(select(Job).where(Job.id == job_id))
    if job is None:
        logger.info("Job %s não existe mais; evento não fechado", job_id)
        return None

    evento = await _evento_do_job(db, job_id)
    if evento.rate_snapshot and not _promove(evento.status, status):
        logger.debug("Evento do job %s já fechado; nada a fazer", job_id)
        return evento

    # A evidência de que a transcrição foi paga é a transcrição EXISTIR.
    transcreveu = (
        await db.scalar(
            select(Transcript.id).where(Transcript.job_id == job_id).limit(1)
        )
        is not None
    )
    minutos = (
        Decimal(str(job.duration_seconds or 0)) / Decimal("60")
        if transcreveu
        else Decimal("0")
    )

    config = await costs.get_config(db)
    custo = costs.calcular(
        config,
        transcription_minutes=minutos,
        transcription_provider=settings.transcription_provider,
        analysis_model=evento.analysis_model,
        input_tokens=evento.input_tokens or 0,
        output_tokens=evento.output_tokens or 0,
        cobrar_storage=transcreveu,
    )

    evento.user_id = job.user_id
    evento.source_video_url = job.youtube_url
    evento.source_minutes = Decimal(str(job.duration_seconds or 0)) / Decimal("60")
    evento.transcription_provider = (
        settings.transcription_provider if transcreveu else None
    )
    evento.transcription_minutes = minutos
    evento.transcription_cost_usd = custo.transcription_cost_usd
    evento.analysis_cost_usd = custo.analysis_cost_usd
    evento.storage_cost_usd = custo.storage_cost_usd
    evento.total_cost_usd = custo.total_cost_usd
    evento.total_cost_brl = custo.total_cost_brl
    evento.rate_snapshot = custo.rate_snapshot
    evento.status = status
    evento.credits_charged = await _creditos_cobrados(db, job_id)
    await db.flush()

    if evento.credits_charged == 0 and custo.total_cost_brl > 0:
        # O caso que o dono pediu para enxergar: gastamos e não recebemos. Vai
        # para o log além do painel, para aparecer sem ninguém abrir a tela.
        logger.warning(
            "Job %s (%s) custou R$ %s e não foi cobrado do usuário",
            job_id,
            status,
            custo.total_cost_brl,
        )
    return evento


async def fechar_job(job_id: str, *, status: str) -> None:
    """`fechar` com sessão própria, para o pipeline chamar em uma linha."""
    from app.database import AsyncSessionLocal

    try:
        async with AsyncSessionLocal() as db:
            await fechar(db, job_id, status=status)
            await db.commit()
    except Exception:  # noqa: BLE001 - medição não derruba pipeline
        logger.exception(
            "Falha ao fechar o evento de custo do job %s — este vídeo vai "
            "faltar no monitor",
            job_id,
        )
