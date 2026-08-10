"""
Orquestrador do pipeline de processamento de vídeo.

Fluxo:
  queued → downloading → transcribing → analyzing → clipping → done
  (qualquer etapa pode ir para: error)

Cada etapa atualiza o status do job no banco de dados antes de executar.
O pipeline nunca crasha silenciosamente — erros são capturados e persistidos.

Recuperação de interrupções
---------------------------
O pipeline roda em BackgroundTasks, DENTRO do processo do servidor: se o
processo morre (reload do uvicorn ao salvar um arquivo, queda, Ctrl+C), o job
para onde estava e não volta sozinho. Duas peças cobrem isso:

  - reconcile_interrupted_jobs(): no startup, marca como 'error' os jobs que
    ficaram presos num status de execução — ninguém mais está trabalhando neles;
  - run_pipeline(job_id, resume=True): retoma reaproveitando tudo que já está em
    disco e no banco (vídeo, áudio, transcrição, análise, clips renderizados).
    Só refaz o que falta — nada de re-baixar o vídeo ou pagar a API de novo.
"""

import asyncio
import json
import logging
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import select, update

from app.database import AsyncSessionLocal
from app.models import Job, Transcript, Clip
from app.services.downloader import VideoMetadata, download_video
from app.services.transcriber import transcribe_audio
from app.services.analyzer import analyze_virality
from app.services.clipper import cut_and_crop, cut_and_stack
from app.services.facecam import (
    CamPhase,
    default_rect,
    detect_facecam_phases,
    rect_from_dict,
    single_phase,
)
from app.services.layout import streamer_geometry
from app.workers import joblock

logger = logging.getLogger(__name__)

# Status em que alguém está ativamente trabalhando no job. Se o processo morre,
# ninguém está — e o job fica preso nesse status para sempre.
RUNNING_STATUSES = ("queued", "downloading", "transcribing", "analyzing", "clipping")

INTERRUPTED_MESSAGE = (
    "Processamento interrompido: o servidor reiniciou durante o job. "
    "Use 'Retomar' — o download, a transcrição e a análise já feitos são "
    "reaproveitados, só os clips que faltam são renderizados."
)


@dataclass
class _ClipTask:
    """Um clip a renderizar — vindo de uma análise nova ou já salvo no banco."""

    clip_id: str
    start: float
    end: float
    banner_text: str
    rendered: bool = False


async def _update_job_status(job_id: str, status: str, **kwargs) -> None:
    """Atualiza status e campos opcionais do job no banco."""
    async with AsyncSessionLocal() as db:
        result = await db.execute(select(Job).where(Job.id == job_id))
        job = result.scalar_one_or_none()
        if not job:
            logger.error(f"[{job_id}] Job not found when updating status to '{status}'")
            return
        job.status = status
        job.updated_at = datetime.now(timezone.utc)
        for key, value in kwargs.items():
            setattr(job, key, value)
        await db.commit()
        logger.info(f"[{job_id}] Status → {status}")


async def _update_clip(clip_id: str, status: str, **kwargs) -> None:
    """Atualiza status e campos opcionais de um clip."""
    async with AsyncSessionLocal() as db:
        result = await db.execute(select(Clip).where(Clip.id == clip_id))
        clip = result.scalar_one_or_none()
        if not clip:
            logger.warning(f"Clip {clip_id} not found when marking '{status}'")
            return
        clip.status = status
        for key, value in kwargs.items():
            setattr(clip, key, value)
        await db.commit()


async def reconcile_interrupted_jobs() -> list[str]:
    """
    Marca como 'error' os jobs presos num status de execução.

    Chamado no startup do servidor: um job nesses status normalmente é órfão de
    um processo que já morreu. Sem isso o job fica em 'clipping' para sempre e o
    frontend faz polling eterno.

    Jobs com lock ativo são poupados — há outro processo (ex.: um
    `app.scripts.resume_job` rodando por fora) trabalhando neles agora.

    Retorna os IDs reconciliados.
    """
    async with AsyncSessionLocal() as db:
        result = await db.execute(select(Job).where(Job.status.in_(RUNNING_STATUSES)))
        jobs = [
            job for job in result.scalars().all()
            if not _skip_locked(job.id)
        ]
        if not jobs:
            return []

        job_ids = [job.id for job in jobs]
        now = datetime.now(timezone.utc)
        for job in jobs:
            job.status = "error"
            job.error_message = INTERRUPTED_MESSAGE
            job.updated_at = now

        # Clips em 'processing' são órfãos pelo mesmo motivo; sem isso a UI
        # mostra spinner infinito neles.
        await db.execute(
            update(Clip)
            .where(Clip.job_id.in_(job_ids), Clip.status == "processing")
            .values(status="error")
        )
        await db.commit()

    logger.warning(
        f"{len(job_ids)} job(s) interrompido(s) por restart marcado(s) como erro: "
        f"{', '.join(job_ids)}"
    )
    return job_ids


def _skip_locked(job_id: str) -> bool:
    """True se outro processo vivo está trabalhando neste job."""
    pid = joblock.owner_pid(job_id)
    if pid is None:
        return False
    logger.info(f"[{job_id}] Em processamento pelo PID {pid} — não reconciliado")
    return True


def _banner_text(hook: str | None, suggested_title: str | None) -> str:
    """Texto da pílula vermelha do layout 'cover'."""
    return hook or suggested_title or ""


def _media_from_job(saved: dict) -> VideoMetadata | None:
    """
    Reconstrói os metadados do download a partir do job, se o vídeo e o áudio
    ainda estiverem em disco. None = precisa baixar de novo.
    """
    video_path = saved["video_path"]
    audio_path = saved["audio_path"]
    if not (video_path and audio_path):
        return None
    if not (Path(video_path).is_file() and Path(audio_path).is_file()):
        return None
    return VideoMetadata(
        title=saved["video_title"] or "Unknown Title",
        channel=saved["channel_name"] or "Unknown Channel",
        duration=saved["duration_seconds"] or 0.0,
        thumbnail_url=saved["thumbnail_url"],
        video_path=video_path,
        audio_path=audio_path,
    )


async def _words_from_disk(job_id: str) -> list[dict] | None:
    """
    Palavras da transcrição já feita (registro no banco + JSON em disco).
    None = transcrever de novo.
    """
    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(Transcript).where(Transcript.job_id == job_id)
        )
        transcript = result.scalars().first()

    if not transcript:
        return None

    path = Path(transcript.words_json_path)
    if not path.is_file():
        logger.warning(f"[{job_id}] Words JSON ausente ({path}) — refazendo transcrição")
        return None

    try:
        with path.open(encoding="utf-8") as f:
            words = json.load(f)
    except (json.JSONDecodeError, OSError) as exc:
        logger.warning(f"[{job_id}] Words JSON ilegível ({exc}) — refazendo transcrição")
        return None

    return words or None


async def _tasks_from_db(job_id: str) -> list[_ClipTask]:
    """
    Clips já criados por uma análise anterior. Lista vazia = precisa analisar.

    Um clip só conta como renderizado se estiver 'ready' E o arquivo existir —
    arquivo parcial de um render interrompido é re-renderizado.
    """
    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(Clip).where(Clip.job_id == job_id).order_by(Clip.start_time)
        )
        clips = result.scalars().all()

    return [
        _ClipTask(
            clip_id=clip.id,
            start=clip.start_time,
            end=clip.end_time,
            banner_text=_banner_text(clip.hook, clip.suggested_title),
            rendered=(
                clip.status == "ready"
                and bool(clip.file_path)
                and Path(clip.file_path).is_file()
            ),
        )
        for clip in clips
    ]


async def _create_clip_records(
    job_id: str,
    viral_clips: list,
    words: list[dict],
    subtitle_mode: str,
) -> list[_ClipTask]:
    """Persiste os clips escolhidos pela análise com status 'processing'."""
    tasks: list[_ClipTask] = []

    async with AsyncSessionLocal() as db:
        for vc in viral_clips:
            excerpt_words = [
                w["text"] for w in words
                if w["start"] >= vc.start and w["end"] <= vc.end
            ]
            excerpt = " ".join(excerpt_words[:50])  # max 50 palavras no excerpt

            clip = Clip(
                job_id=job_id,
                start_time=vc.start,
                end_time=vc.end,
                duration=vc.end - vc.start,
                virality_score=vc.score,
                hook=vc.hook,
                reason=vc.reason,
                tags_json=json.dumps(vc.tags),
                suggested_title=vc.suggested_title,
                transcript_excerpt=excerpt,
                part_number=vc.part_number,
                subtitle_mode=subtitle_mode,
                status="processing",
            )
            db.add(clip)
            await db.flush()  # gera o ID
            tasks.append(
                _ClipTask(
                    clip_id=clip.id,
                    start=vc.start,
                    end=vc.end,
                    banner_text=_banner_text(vc.hook, vc.suggested_title),
                )
            )

        await db.commit()

    return tasks


def _manual_rect(facecam_json: str | None):
    """
    Caixa que o USUÁRIO informou no job (None se não houver ou for ilegível).

    A caixa que o detector gravou no job também mora nesta coluna, mas serve só
    para a UI mostrar o que foi usado: aceitá-la aqui congelaria a detecção do
    primeiro clip para o job inteiro num resume — exatamente o que a detecção
    por clip existe para evitar. O método distingue as duas (o payload do
    usuário não traz método, e rect_from_dict assume 'manual').
    """
    if not facecam_json:
        return None
    try:
        rect = rect_from_dict(json.loads(facecam_json))
    except json.JSONDecodeError:
        return None
    return rect if rect and rect.method == "manual" else None


async def _resolve_facecam(
    job_id: str,
    video_path: str,
    facecam_json: str | None,
    start_time: float,
    end_time: float,
    store: bool,
) -> list[CamPhase]:
    """
    Linha do tempo da facecam PARA ESTE CLIP, nesta ordem:
      1. a caixa informada pelo usuário (vale para o job inteiro);
      2. detecção automática no trecho do próprio clip;
      3. canto inferior direito (palpite) — o render nunca falha por isso.

    A detecção é por clip, e não uma vez por job, porque o layout da live muda
    ao longo do vídeo: a cam que estava à direita no minuto 3 pode estar à
    esquerda no minuto 40. Dentro do clip, as mudanças viram fases (o painel
    troca de recorte na hora certa).

    Com store=True o resultado vai para o job — é o que a UI mostra e o usuário
    edita. Só o primeiro clip grava, senão cada clip sobrescreveria o anterior.
    """
    duration = end_time - start_time

    manual = _manual_rect(facecam_json)
    if manual:
        logger.info(f"[{job_id}] Facecam: using rect from job ({manual.method})")
        return single_phase(manual, duration)

    geo = streamer_geometry()
    phases = await asyncio.to_thread(
        detect_facecam_phases, video_path, start_time, end_time, geo.facecam_aspect
    )
    if not phases:
        phases = single_phase(default_rect(geo.facecam_aspect), duration)
        logger.warning(
            f"[{job_id}] Facecam not found — falling back to bottom-right corner. "
            f"Ajuste a caixa no job para corrigir o enquadramento."
        )

    if store:
        dominant = max(phases, key=lambda p: p.end - p.start).rect
        await _update_job_status(
            job_id, "clipping", facecam_rect=json.dumps(dominant.as_dict())
        )
    return phases


async def run_pipeline(job_id: str, resume: bool = False) -> None:
    """
    Executa o pipeline completo de processamento para um job.

    Etapas:
      1. Download do vídeo (yt-dlp)
      2. Transcrição (AssemblyAI)
      3. Análise de viralidade (Claude API)
      4. Corte e legendagem dos clips (FFmpeg)

    Atualiza o status do job a cada etapa. Em caso de erro,
    persiste a mensagem de erro e muda status para 'error'.

    Com resume=True cada etapa é pulada quando o resultado dela ainda existe
    (arquivo em disco + registro no banco): retomar um job interrompido não
    re-baixa o vídeo, não paga transcrição/análise de novo e não re-renderiza
    os clips que já ficaram prontos.
    """
    # O lock avisa ao startup do servidor que este job tem dono vivo — sem ele,
    # um reload durante o trabalho marcaria o job como interrompido.
    with joblock.held(job_id):
        await _execute_pipeline(job_id, resume)


async def _execute_pipeline(job_id: str, resume: bool) -> None:
    logger.info(f"[{job_id}] Pipeline started (resume={resume})")

    try:
        # ── 1. Busca dados do job ─────────────────────────────────────────────
        async with AsyncSessionLocal() as db:
            result = await db.execute(select(Job).where(Job.id == job_id))
            job = result.scalar_one_or_none()
            if not job:
                logger.error(f"[{job_id}] Job not found at pipeline start")
                return
            youtube_url = job.youtube_url
            subtitle_mode = job.subtitle_mode
            layout_mode = job.layout_mode or "cover"
            facecam_json = job.facecam_rect
            saved_media = {
                "video_title": job.video_title,
                "channel_name": job.channel_name,
                "duration_seconds": job.duration_seconds,
                "thumbnail_url": job.thumbnail_url,
                "video_path": job.video_path,
                "audio_path": job.audio_path,
            }

        # ── 2. Download ───────────────────────────────────────────────────────
        metadata = _media_from_job(saved_media) if resume else None
        if metadata:
            logger.info(f"[{job_id}] Resume: vídeo e áudio em disco — download pulado")
        else:
            await _update_job_status(job_id, "downloading")
            metadata = await download_video(job_id, youtube_url)

        await _update_job_status(
            job_id,
            "transcribing",
            video_title=metadata.title,
            channel_name=metadata.channel,
            duration_seconds=metadata.duration,
            thumbnail_url=metadata.thumbnail_url,
            video_path=metadata.video_path,
            audio_path=metadata.audio_path,
        )

        # ── 3. Transcrição ────────────────────────────────────────────────────
        words = await _words_from_disk(job_id) if resume else None
        if words:
            logger.info(
                f"[{job_id}] Resume: transcrição reaproveitada ({len(words)} palavras)"
            )
        else:
            transcription = await transcribe_audio(job_id, metadata.audio_path)

            async with AsyncSessionLocal() as db:
                transcript_record = Transcript(
                    job_id=job_id,
                    full_text=transcription.full_text,
                    words_json_path=transcription.words_json_path,
                    language=transcription.language,
                    confidence=transcription.confidence,
                )
                db.add(transcript_record)
                await db.commit()
                logger.info(f"[{job_id}] Transcript saved (id={transcript_record.id})")

            words = [asdict(w) for w in transcription.words]

        # ── 4. Análise de viralidade ──────────────────────────────────────────
        tasks = await _tasks_from_db(job_id) if resume else []
        if tasks:
            logger.info(
                f"[{job_id}] Resume: {len(tasks)} clip(s) da análise anterior "
                f"({sum(t.rendered for t in tasks)} já renderizado(s)) — análise pulada"
            )
        else:
            await _update_job_status(job_id, "analyzing")

            analysis = await analyze_virality(
                job_id=job_id,
                words=words,
                title=metadata.title,
                channel=metadata.channel,
                duration_seconds=metadata.duration,
            )

            logger.info(
                f"[{job_id}] Analysis complete: {len(analysis.clips)} clips to generate"
            )

            if not analysis.clips:
                await _update_job_status(job_id, "done")
                logger.info(f"[{job_id}] No viral clips found. Pipeline complete.")
                return

            tasks = await _create_clip_records(
                job_id, analysis.clips, words, subtitle_mode
            )
            logger.info(f"[{job_id}] Created {len(tasks)} clip records")

        # ── 5. Corte dos clips ────────────────────────────────────────────────
        await _update_job_status(job_id, "clipping")

        pending = [t for t in tasks if not t.rendered]
        if not pending:
            await _update_job_status(job_id, "done")
            logger.info(f"[{job_id}] Todos os clips já estavam prontos. Pipeline complete!")
            return

        # Num resume os pendentes estão como 'error': voltam todos para a fila
        # de uma vez, senão a UI mostra a lista inteira em vermelho enquanto os
        # clips são refeitos um a um.
        async with AsyncSessionLocal() as db:
            await db.execute(
                update(Clip)
                .where(Clip.id.in_([t.clip_id for t in pending]))
                .values(status="processing")
            )
            await db.commit()

        # Processa cada clip pendente
        failures: list[str] = []
        for index, task in enumerate(pending):
            try:
                if layout_mode == "streamer":
                    # O layout da live muda ao longo do vídeo: cada clip tem a
                    # sua própria linha do tempo de facecam.
                    facecam = await _resolve_facecam(
                        job_id=job_id,
                        video_path=metadata.video_path,
                        facecam_json=facecam_json,
                        start_time=task.start,
                        end_time=task.end,
                        store=index == 0,
                    )
                    file_path, file_size = await cut_and_stack(
                        job_id=job_id,
                        clip_id=task.clip_id,
                        video_path=metadata.video_path,
                        start_time=task.start,
                        end_time=task.end,
                        words=words,
                        subtitle_mode=subtitle_mode,
                        facecam=facecam,
                        streamer_name=metadata.channel,
                    )
                else:
                    file_path, file_size = await cut_and_crop(
                        job_id=job_id,
                        clip_id=task.clip_id,
                        video_path=metadata.video_path,
                        start_time=task.start,
                        end_time=task.end,
                        words=words,
                        subtitle_mode=subtitle_mode,
                        banner_text=task.banner_text,
                    )

                await _update_clip(
                    task.clip_id,
                    "ready",
                    file_path=file_path,
                    file_size_bytes=file_size,
                )
                logger.info(f"[{job_id}] Clip {task.clip_id} ready: {file_path}")

            except Exception as e:
                logger.error(
                    f"[{job_id}] Failed to process clip {task.clip_id}: {e}",
                    exc_info=True,
                )
                failures.append(str(e))
                await _update_clip(task.clip_id, "error")

        # ── 6. Finaliza ───────────────────────────────────────────────────────
        # Nenhum clip renderizado = o job falhou, mesmo tendo chegado até aqui.
        # Sem isso a UI mostra "Pronto / 100%" com a lista de clips toda em erro.
        if len(failures) == len(tasks):
            raise RuntimeError(
                f"Nenhum clip pôde ser renderizado ({len(failures)} falha(s)). "
                f"Primeiro erro: {failures[0][:500]}"
            )

        if failures:
            logger.warning(
                f"[{job_id}] {len(failures)} of {len(pending)} clip(s) failed to render"
            )

        await _update_job_status(job_id, "done")
        logger.info(f"[{job_id}] Pipeline complete!")

    except Exception as e:
        logger.error(f"[{job_id}] Pipeline failed: {e}", exc_info=True)
        await _update_job_status(job_id, "error", error_message=str(e))
