import json
import logging
import shutil
from typing import List, Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import delete, select, update
from sqlalchemy.orm import selectinload

from app.config import settings
from app.database import get_db
from app.deps import current_user, owned_by
from app.features import SourceTypeField, billing_enabled
from app.layouts import LAYOUT_LABELS, layout_allowed, layouts_for
from app.models import Clip, CreditLedger, Job, Profile, Transcript, User
from app.prompts.viral_analysis import default_source_type
from app.schemas import JobCreate, JobResponse, JobDetailResponse
from app.services import usage, usage_monitor
from app.services.quota import guard_new_job
from app.utils.timecodes import parse_ranges
from app.workers import joblock
from app.workers.pipeline import RUNNING_STATUSES, run_pipeline

logger = logging.getLogger(__name__)

router = APIRouter(tags=["jobs"])


async def _job_do_usuario(job_id: str, user: User, db: AsyncSession) -> Job:
    """O job, se ele for desta pessoa. 404 se não for.

    404 e não 403, de propósito: um 403 confirmaria que o job existe, e daria
    para varrer ids descobrindo o que os outros estão processando. Para quem não
    é dono, o job simplesmente não existe.
    """
    result = await db.execute(
        select(Job).where(Job.id == job_id, owned_by(user))
    )
    job = result.scalar_one_or_none()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return job


@router.post("/jobs", response_model=JobResponse, status_code=201)
async def create_job(
    payload: JobCreate,
    background_tasks: BackgroundTasks,
    user: User = Depends(current_user),
    db: AsyncSession = Depends(get_db),
) -> Job:
    """Cria um novo job de processamento e inicia o pipeline em background.

    As travas de custo rodam ANTES de o job existir: duração do vídeo, cota da
    janela e duplicata. Recusar depois do download já teria custado exatamente o
    que elas existem para evitar (ver services/quota.py).
    """
    duration = await guard_new_job(db, user, payload.youtube_url)

    # O perfil é quem FORNECE o nicho, não quem o substitui: o job continua
    # gravando `source_type`, e é ele que o pipeline lê daqui para baixo. Assim
    # editar ou excluir o perfil depois não muda a rubrica de um job já feito.
    perfil = None
    if payload.profile_id:
        perfil = (
            await db.execute(
                select(Profile).where(
                    Profile.id == payload.profile_id, Profile.user_id == user.id
                )
            )
        ).scalar_one_or_none()
        if not perfil:
            raise HTTPException(status_code=404, detail="Perfil não encontrado")

    # A rubrica primeiro: é ela que decide quais layouts existem.
    nicho = (
        payload.source_type
        or (perfil.source_type if perfil else None)
        or default_source_type(payload.layout_mode)
    )

    # O layout depois. Informado, tem que servir à rubrica — a capa é escolhida
    # pelo rosto mais expressivo (não existe em gameplay) e a facecam empilhada
    # não existe em podcast. Omitido, cai no padrão do perfil e, sem perfil, no
    # primeiro que a rubrica aceita.
    layout = payload.layout_mode
    if layout and not layout_allowed(layout, nicho):
        permitidos = ", ".join(LAYOUT_LABELS[l][0] for l in layouts_for(nicho))
        raise HTTPException(
            status_code=422,
            detail=(
                f"O layout escolhido não serve à rubrica {nicho}. "
                f"Disponíveis: {permitidos}."
            ),
        )
    if not layout:
        do_perfil = perfil.default_layout_mode if perfil else None
        layout = (
            do_perfil
            if do_perfil and layout_allowed(do_perfil, nicho)
            else layouts_for(nicho)[0]
        )

    job = Job(
        user_id=user.id,
        profile_id=perfil.id if perfil else None,
        youtube_url=payload.youtube_url,
        # Já medida na consulta de metadados. Guardar agora é o que faz a cota
        # do PRÓXIMO pedido contar este vídeo antes de o download terminar —
        # sem isso, dez pedidos disparados juntos passariam todos.
        duration_seconds=duration or None,
        subtitle_mode=payload.subtitle_mode,
        layout_mode=layout,
        # Omitido pelo cliente: infere pelo layout, que é o palpite certo na
        # maioria dos casos (streamer→gameplay, cover→podcast).
        # Ordem de precedência: o que o cliente mandou, senão o do perfil,
        # senão o palpite pelo layout — que é como sempre funcionou.
        source_type=nicho,
        clip_mode=payload.clip_mode,
        # Guardado já em segundos: a anotação "3:24" é conveniência de quem
        # digita, não formato de trabalho. A ORDEM digitada é preservada.
        manual_clips=(
            json.dumps([list(r) for r in parse_ranges(payload.manual_clips)])
            if payload.manual_clips
            else None
        ),
        manual_mode=payload.manual_mode,
        # Sem caixa informada, o pipeline detecta a facecam clip a clip
        facecam_rect=(
            payload.facecam_rect.model_dump_json() if payload.facecam_rect else None
        ),
        status="queued",
    )
    db.add(job)

    # A reserva de crédito vai na MESMA transação que cria o job, e é ela a
    # trava de custo real do produto: sem saldo, o job não chega a existir. O
    # flush antes é para a linha do job já existir quando o lançamento
    # referenciar a chave estrangeira dela.
    #
    # `segurar` levanta 402 quando falta saldo, e é esse código que a interface
    # usa para mandar a pessoa à tela de recarga — a transação inteira volta
    # atrás, sem job órfão e sem crédito preso.
    if billing_enabled():
        await db.flush()
        await usage.segurar(
            db, user_id=user.id, job_id=job.id, segundos=duration or 0.0
        )

    await db.commit()
    await db.refresh(job)

    logger.info(f"Job {job.id} created for URL: {payload.youtube_url}")
    background_tasks.add_task(run_pipeline, job.id)

    return job


@router.get("/jobs", response_model=List[JobResponse])
async def list_jobs(
    source: Optional[SourceTypeField] = None,
    profile_id: Optional[str] = None,
    user: User = Depends(current_user),
    db: AsyncSession = Depends(get_db),
) -> List[Job]:
    """
    Os jobs DESTE usuário, em ordem decrescente de criação.

    Dois filtros, e os dois continuam valendo:

      - `profile_id` — o que a nova organização usa: os jobs daquele perfil;
      - `source` — o filtro por nicho, que existia antes dos perfis. Continua
        aqui porque é como os jobs anteriores são alcançáveis: eles não têm
        perfil, e sumir com eles seria perder trabalho de vista.
    """
    query = select(Job).where(owned_by(user)).order_by(Job.created_at.desc())
    if profile_id:
        query = query.where(Job.profile_id == profile_id)
    if source:
        query = query.where(Job.source_type == source)
    result = await db.execute(query)
    return result.scalars().all()


@router.get("/jobs/{job_id}", response_model=JobDetailResponse)
async def get_job(
    job_id: str,
    user: User = Depends(current_user),
    db: AsyncSession = Depends(get_db),
) -> Job:
    """Retorna detalhes do job incluindo todos os clips gerados."""
    result = await db.execute(
        select(Job)
        .options(selectinload(Job.clips))
        .where(Job.id == job_id, owned_by(user))
    )
    job = result.scalar_one_or_none()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    # Os créditos deste job, para a tela dizer o que foi gasto e com quanto a
    # pessoa ficou. Vêm anexados à instância e não são colunas de `jobs`: o
    # extrato é a fonte, e duplicar o valor numa coluna daria dois números que
    # poderiam discordar. Ficam nulos quando não há cobrança — versão pessoal,
    # ou job criado antes dela.
    if billing_enabled():
        await _anexar_creditos(job, user, db)

    return job


async def _anexar_creditos(job: Job, user: User, db: AsyncSession) -> None:
    lancamentos = (
        await db.execute(
            select(CreditLedger).where(CreditLedger.ref_usage_id == job.id)
        )
    ).scalars().all()
    if not lancamentos:
        return

    for lanc in lancamentos:
        if lanc.tipo == "hold":
            job.creditos_reservados = -int(lanc.amount)
        elif lanc.tipo == "debito":
            job.creditos_cobrados = -int(lanc.amount)
    job.saldo = int(user.credit_balance or 0)


def _was_auto_detected(facecam_json: str | None) -> bool:
    """True se a caixa da facecam salva veio do detector (e não do usuário)."""
    if not facecam_json:
        return False
    try:
        stored = json.loads(facecam_json)
    except json.JSONDecodeError:
        return True  # ilegível: melhor detectar de novo
    return isinstance(stored, dict) and stored.get("method", "manual") != "manual"


@router.post("/jobs/{job_id}/retry", response_model=JobResponse, status_code=202)
async def retry_job(
    job_id: str,
    background_tasks: BackgroundTasks,
    user: User = Depends(current_user),
    db: AsyncSession = Depends(get_db),
) -> Job:
    """
    Retoma um job que falhou ou foi interrompido, reaproveitando o que já ficou
    pronto: o vídeo baixado, a transcrição, a análise e os clips renderizados.
    Só o que falta é refeito — sem re-download e sem custo de API.

    Também serve para um job 'done' com clips que falharam: re-renderiza só eles.
    """
    job = await _job_do_usuario(job_id, user, db)
    owner = joblock.owner_pid(job_id)
    if job.status in RUNNING_STATUSES or owner is not None:
        raise HTTPException(
            status_code=409,
            detail="O job já está em processamento.",
        )

    job.status = "queued"
    job.error_message = None
    if _was_auto_detected(job.facecam_rect):
        # Caixa que veio da detecção é descartada — o retry re-detecta e pega as
        # melhorias do detector. A que o usuário informou à mão é preservada.
        job.facecam_rect = None
    # Clips que falharam voltam para a fila; os 'ready' são preservados.
    await db.execute(
        update(Clip)
        .where(Clip.job_id == job_id, Clip.status == "error")
        .values(status="processing")
    )
    await db.commit()
    await db.refresh(job)

    logger.info(f"Job {job_id} retomado (resume)")
    background_tasks.add_task(run_pipeline, job_id, True)

    return job


@router.delete("/jobs/{job_id}", status_code=204)
async def delete_job(
    job_id: str,
    user: User = Depends(current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    """
    Exclui o job e tudo associado a ele: clips e transcript no banco,
    vídeo/áudio baixados, clips renderizados e o JSON de palavras.

    Jobs em andamento também podem ser excluídos (cobre jobs travados após
    restart); o pipeline detecta a ausência do job e encerra sem crashar.
    """
    job = await _job_do_usuario(job_id, user, db)

    # Devolver a reserva ANTES de apagar. Um job apagado com reserva de pé
    # deixaria o crédito preso para sempre: quem devolveria é o pipeline, e ele
    # não vai mais rodar. Não tem efeito nenhum num job já concluído — lá a
    # reserva já foi devolvida e o consumo já foi cobrado.
    await usage.reconciliar(db, job_id=job_id, segundos_reais=None, sucesso=False)
    await db.commit()

    # Fecha o custo ANTES de apagar: depois do DELETE os dados do job já não
    # existem, e o gasto com transcrição deste vídeo sumiria do monitor junto
    # com ele. `deleted` fica separado de `failed` porque a causa é outra.
    await usage_monitor.fechar(db, job_id, status="deleted")

    # Registros no banco (sem FK cascade configurado — remoção explícita)
    await db.execute(delete(Clip).where(Clip.job_id == job_id))
    await db.execute(delete(Transcript).where(Transcript.job_id == job_id))
    await db.delete(job)
    await db.commit()

    # Arquivos no storage (caminhos derivados do ID, não do banco)
    shutil.rmtree(settings.downloads_dir / job_id, ignore_errors=True)
    shutil.rmtree(settings.clips_dir / job_id, ignore_errors=True)
    words_json = settings.transcripts_dir / f"{job_id}_words.json"
    words_json.unlink(missing_ok=True)
    (settings.locks_dir / f"{job_id}.pid").unlink(missing_ok=True)

    logger.info(f"Job {job_id} deleted (records + storage)")
