import asyncio
import json
import logging
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    File,
    Form,
    HTTPException,
    Response,
    UploadFile,
)
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import delete, select, update
from sqlalchemy.orm import selectinload

from app.config import settings
from app.database import get_db
from app.deps import current_user, owned_by
from app.features import SourceTypeField, billing_enabled
from app.layouts import LAYOUT_LABELS, layout_allowed, layouts_for
from app.models import Clip, CreditLedger, FacecamReport, Job, Profile, Transcript, User
from app.prompts.viral_analysis import default_source_type
from app.schemas import (
    FacecamRectPayload,
    JobCreate,
    JobDetailResponse,
    JobResponse,
)
from app.services import credits, facecam_review, usage, usage_monitor
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

    # Retomar um job cuja reserva já foi DEVOLVIDA é uma compra: ele falhou,
    # o crédito voltou, e agora vai entregar os clips. Cobra-se no fim, mas a
    # porta é aqui — deixar entrar sem saldo seria renderizar o vídeo inteiro
    # para descobrir na última linha que não há como cobrar. Devolve 402, o
    # mesmo que a criação de job, e a interface manda para a recarga.
    necessario = await usage.creditos_para_retomar(
        db, job_id=job.id, segundos=job.duration_seconds
    )
    if necessario > 0:
        disponivel = await credits.saldo(db, user.id)
        if disponivel < necessario:
            raise credits.SaldoInsuficiente(
                necessario=necessario, disponivel=disponivel
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


# ─── Enquadramento da facecam: relatar, destravar, corrigir ───────────────────
#
# A caixa da cam é detectada por heurística, e heurística erra. Quando erra, o
# painel de cima sai com gameplay dentro e a cabeça cortada — clipe pago que não
# presta. Corrigir exige servir quadros do vídeo e re-renderizar, e as duas
# coisas custam CPU: por isso o corretor é DESTRANCADO por um relato aprovado,
# em vez de ficar aberto para quem quiser clicar.

_TIPOS_DE_PRINT = {"image/png": ".png", "image/jpeg": ".jpg", "image/webp": ".webp"}
_PRINT_MAX_BYTES = 8 * 1024 * 1024

#: Assinatura no início do arquivo, por tipo. O `content_type` do upload é
#: escolhido por quem envia e não prova nada — conferir os bytes é o que impede
#: gravar em disco algo que não é imagem, com extensão de imagem.
_ASSINATURAS = {
    "image/png": (b"\x89PNG\r\n\x1a\n",),
    "image/jpeg": (b"\xff\xd8\xff",),
    "image/webp": (b"RIFF",),
}


def _parece_imagem(conteudo: bytes, media_type: str) -> bool:
    assinaturas = _ASSINATURAS.get(media_type, ())
    if not any(conteudo.startswith(a) for a in assinaturas):
        return False
    # WebP tem o RIFF genérico; o que distingue é o rótulo do formato.
    if media_type == "image/webp":
        return conteudo[8:12] == b"WEBP"
    return True


class FacecamReportResponse(BaseModel):
    id: str
    clip_id: str | None
    status: str
    veredito: str | None
    description: str
    # O intervalo do clipe relatado: é o que a linha do tempo do corretor varre.
    # Fazer a pessoa procurar o instante no vídeo inteiro seria trabalho que o
    # banco já sabe evitar.
    clip_start: float | None = None
    clip_end: float | None = None

    model_config = {"from_attributes": True}


async def _relato_atual(job_id: str, db: AsyncSession) -> FacecamReport | None:
    """O relato mais recente deste job."""
    return await db.scalar(
        select(FacecamReport)
        .where(FacecamReport.job_id == job_id)
        .order_by(FacecamReport.created_at.desc())
        .limit(1)
    )


async def _com_intervalo(
    relato: FacecamReport, db: AsyncSession
) -> FacecamReportResponse:
    resposta = FacecamReportResponse.model_validate(relato)
    if relato.clip_id:
        clip = await db.scalar(select(Clip).where(Clip.id == relato.clip_id))
        if clip:
            resposta.clip_start = clip.start_time
            resposta.clip_end = clip.end_time
    return resposta


@router.get("/jobs/{job_id}/facecam-report", response_model=FacecamReportResponse | None)
async def get_facecam_report(
    job_id: str,
    user: User = Depends(current_user),
    db: AsyncSession = Depends(get_db),
) -> FacecamReportResponse | None:
    """O relato deste job, se houver. `null` é resposta, não erro."""
    await _job_do_usuario(job_id, user, db)
    relato = await _relato_atual(job_id, db)
    return await _com_intervalo(relato, db) if relato else None


@router.post(
    "/jobs/{job_id}/facecam-report",
    response_model=FacecamReportResponse,
    status_code=201,
)
async def create_facecam_report(
    job_id: str,
    clip_id: str = Form(...),
    description: str = Form(...),
    file: UploadFile = File(...),
    user: User = Depends(current_user),
    db: AsyncSession = Depends(get_db),
) -> FacecamReportResponse:
    """Recebe o print, tria com a visão e destrava a correção se procede."""
    job = await _job_do_usuario(job_id, user, db)
    if job.layout_mode != "streamer":
        raise HTTPException(
            status_code=422,
            detail="Só o layout de streamer tem painel de facecam para enquadrar.",
        )

    ext = _TIPOS_DE_PRINT.get((file.content_type or "").lower())
    if ext is None:
        raise HTTPException(
            status_code=422, detail="Mande o print em PNG, JPEG ou WebP."
        )
    conteudo = await file.read()
    if len(conteudo) > _PRINT_MAX_BYTES:
        raise HTTPException(status_code=413, detail="O print passa de 8 MB.")
    if not conteudo:
        raise HTTPException(status_code=422, detail="O arquivo veio vazio.")
    if not _parece_imagem(conteudo, (file.content_type or "").lower()):
        raise HTTPException(
            status_code=422,
            detail="O arquivo não é a imagem que diz ser. Mande o print de novo.",
        )

    texto = (description or "").strip()
    if len(texto) < 5:
        raise HTTPException(
            status_code=422,
            detail="Descreva em uma frase o que está errado no enquadramento.",
        )

    destino = Path(settings.storage_dir) / "facecam_reports"
    destino.mkdir(parents=True, exist_ok=True)
    relato = FacecamReport(
        job_id=job_id,
        clip_id=clip_id or None,
        user_id=user.id,
        description=texto[:1000],
        screenshot_path="",
    )
    caminho = destino / f"{relato.id}{ext}"
    caminho.write_bytes(conteudo)
    relato.screenshot_path = str(caminho)

    ruim, motivo = await facecam_review.avaliar(
        conteudo, (file.content_type or "image/png").lower(), texto
    )
    relato.status = "aprovado" if ruim else "recusado"
    relato.veredito = motivo
    relato.resolved_at = datetime.now(timezone.utc)

    db.add(relato)
    await db.commit()
    await db.refresh(relato)
    logger.info("Relato de enquadramento %s do job %s: %s", relato.id, job_id, relato.status)
    return await _com_intervalo(relato, db)


async def _relato_aprovado(job_id: str, db: AsyncSession) -> FacecamReport:
    """O relato que destrava o corretor. 403 quando não há."""
    relato = await _relato_atual(job_id, db)
    if relato is None or relato.status != "aprovado":
        raise HTTPException(
            status_code=403,
            detail=(
                "Relate o problema de enquadramento antes de corrigir a caixa: "
                "mande um print e uma descrição."
            ),
        )
    return relato


@router.get("/jobs/{job_id}/frame")
async def get_source_frame(
    job_id: str,
    t: float,
    user: User = Depends(current_user),
    db: AsyncSession = Depends(get_db),
) -> Response:
    """Um quadro do vídeo de ORIGEM, para o corretor desenhar a caixa em cima.

    Exige relato aprovado: extrair quadro de um vídeo de 3 GB é trabalho de
    servidor, e sem a porta qualquer um poderia varrer o vídeo inteiro quadro a
    quadro.

    O instante é preso ao intervalo do clipe relatado. Não é só economia: é o
    trecho que saiu errado, e é onde a cam está no lugar que precisa ser
    corrigido.
    """
    job = await _job_do_usuario(job_id, user, db)
    relato = await _relato_aprovado(job_id, db)
    if not job.video_path:
        raise HTTPException(status_code=404, detail="O vídeo de origem já não está em disco.")

    inicio, fim = 0.0, float(job.duration_seconds or 0)
    if relato.clip_id:
        clip = await db.scalar(select(Clip).where(Clip.id == relato.clip_id))
        if clip:
            inicio, fim = float(clip.start_time), float(clip.end_time)
    instante = min(max(float(t), inicio), max(inicio, fim - 0.1))

    origem = Path(settings.storage_dir).parent / job.video_path
    if not origem.exists():
        origem = Path(job.video_path)
    if not origem.exists():
        raise HTTPException(status_code=404, detail="O vídeo de origem já não está em disco.")

    proc = await asyncio.create_subprocess_exec(
        "ffmpeg", "-hide_banner", "-loglevel", "error",
        "-ss", f"{instante:.3f}", "-i", str(origem),
        "-frames:v", "1", "-q:v", "4", "-f", "image2pipe", "-vcodec", "mjpeg", "pipe:1",
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
    )
    try:
        jpeg, erro = await asyncio.wait_for(proc.communicate(), timeout=30)
    except asyncio.TimeoutError:
        proc.kill()
        raise HTTPException(status_code=504, detail="O vídeo demorou demais para responder.")
    if proc.returncode != 0 or not jpeg:
        logger.warning("Falha ao extrair quadro de %s em %.1fs: %s", job_id, instante, erro[:300])
        raise HTTPException(status_code=500, detail="Não consegui extrair o quadro.")

    # Sem cache: a caixa é ajustada olhando o quadro, e um quadro velho em cache
    # depois de um re-render mostraria o resultado antigo.
    return Response(content=jpeg, media_type="image/jpeg", headers={"Cache-Control": "no-store"})


class FacecamFix(BaseModel):
    facecam_rect: FacecamRectPayload


@router.post("/jobs/{job_id}/facecam-fix", response_model=JobResponse, status_code=202)
async def fix_facecam(
    job_id: str,
    payload: FacecamFix,
    background_tasks: BackgroundTasks,
    user: User = Depends(current_user),
    db: AsyncSession = Depends(get_db),
) -> Job:
    """Grava a caixa corrigida e re-renderiza os clipes deste job.

    **Sem custo.** `usage.reconciliar` não cobra job que já foi cobrado, então
    re-renderizar por erro nosso não tira crédito de ninguém — o cliente já
    pagou por um clipe que deveria ter saído certo da primeira vez.

    A caixa é gravada com `method: manual`, que é como o pipeline distingue o
    que uma PESSOA informou do que o detector achou. Sem isso o retry
    descartaria a correção e detectaria de novo — voltando ao erro.
    """
    job = await _job_do_usuario(job_id, user, db)
    await _relato_aprovado(job_id, db)

    if job.status in RUNNING_STATUSES:
        raise HTTPException(
            status_code=409, detail="Este vídeo ainda está sendo processado."
        )
    if joblock.owner_pid(job_id) is not None:
        raise HTTPException(
            status_code=409, detail="Este vídeo já está sendo processado agora."
        )

    job.facecam_rect = json.dumps(
        {**payload.facecam_rect.model_dump(), "method": "manual"}
    )
    job.status = "queued"
    job.error_message = None
    # Todos os clipes voltam para a fila: a caixa vale para o job inteiro, então
    # re-renderizar só o relatado deixaria os outros com o enquadramento velho.
    await db.execute(
        update(Clip).where(Clip.job_id == job_id).values(status="processing")
    )
    await db.commit()
    await db.refresh(job)

    logger.info("Job %s: caixa da facecam corrigida à mão; re-renderizando", job_id)
    background_tasks.add_task(run_pipeline, job_id, True)
    return job
