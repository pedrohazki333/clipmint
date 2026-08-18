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
import shutil
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import delete, select, update

from app.config import settings
from app.database import AsyncSessionLocal
from app.models import Job, Transcript, Clip
from app.services.downloader import VideoMetadata, download_video, ensure_media
from app.services.transcriber import transcribe_audio
from app.services.analyzer import analyze_virality
from app.services.audio_events import detect_gaps
from app.services.scene_events import describe_events
from app.services.clipper import cut_and_crop, cut_and_stack
from app.services.facecam import (
    CamPhase,
    default_rect,
    detect_facecam_phases,
    rect_from_dict,
    single_phase,
)
from app.prompts.viral_analysis import default_source_type
from app.services.layout import streamer_geometry
from app.services import r6_hud
from app.services import segments as segments_service
from app.services.segments import compact_segments, remap_words
from app.workers import joblock

logger = logging.getLogger(__name__)

# Status em que alguém está ativamente trabalhando no job. Se o processo morre,
# ninguém está — e o job fica preso nesse status para sempre.
RUNNING_STATUSES = ("queued", "downloading", "transcribing", "analyzing", "clipping")

# Acima disto o trecho é o streamer assistindo, não jogando. Medido no job
# do Nesk: o clipe ruim deu 82% e os dois bons deram 0% — o limiar fica no
# meio do vazio entre os dois grupos.
MAX_DEAD_FRACTION = 0.4

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
    # Trechos costurados num clipe só (vazio = corte contínuo)
    segments: list = field(default_factory=list)


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
        if status != "error" and "error_message" not in kwargs:
            # Sair de um erro limpa a mensagem: um resume bem-sucedido não pode
            # deixar o job 'done' exibindo o erro da tentativa anterior.
            job.error_message = None
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


def _parse_segments_json(raw: str | None) -> list[tuple[float, float]]:
    """Trechos costurados salvos no clip; lista vazia = corte contínuo."""
    if not raw:
        return []
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return []
    return [
        (float(item[0]), float(item[1]))
        for item in data
        if isinstance(item, (list, tuple)) and len(item) == 2
    ]


async def _drop_dead_candidates(job_id: str, video_path: str, clips: list) -> list:
    """
    Descarta candidatos em que o streamer passa a maior parte do tempo morto.

    A medição roda só nas janelas candidatas, não no vídeo inteiro: o custo
    acompanha os minutos que viram clipe, não a duração da live.
    """
    if not clips or not r6_hud.template_available():
        return clips

    kept = []
    for clip in clips:
        windows = await r6_hud.find_dead_windows(
            video_path, duration=clip.end - clip.start, start_time=clip.start
        )
        dead = r6_hud.dead_overlap(windows, clip.start, clip.end)
        if dead > MAX_DEAD_FRACTION:
            logger.warning(
                f"[{job_id}] Candidato [{clip.start:.0f}s–{clip.end:.0f}s] "
                f"descartado: streamer morto em {dead:.0%} do trecho"
            )
            continue
        kept.append(clip)

    if len(kept) < len(clips):
        logger.info(f"[{job_id}] {len(clips) - len(kept)} candidato(s) descartado(s) pelo HUD")
    return kept


def _banner_text(hook: str | None, suggested_title: str | None) -> str:
    """Texto da pílula vermelha do layout 'cover'."""
    return hook or suggested_title or ""


async def _media_from_job(job_id: str, saved: dict) -> VideoMetadata | None:
    """
    Reconstrói os metadados do download a partir do job, se o vídeo e o áudio
    ainda estiverem em disco. None = precisa baixar de novo.

    Estar em disco não basta: um download ou uma mesclagem interrompida deixa
    arquivo que abre normalmente mas com o áudio fora do vídeo. Reaproveitar
    isso num resume produz clips do trecho errado, com legenda fora de
    sincronia — o arquivo é conferido antes de ser aceito.
    """
    video_path = saved["video_path"]
    audio_path = saved["audio_path"]
    if not (video_path and audio_path):
        return None
    if not (Path(video_path).is_file() and Path(audio_path).is_file()):
        return None
    if not await ensure_media(
        job_id, video_path, audio_path, saved["duration_seconds"] or 0.0
    ):
        logger.warning(
            f"[{job_id}] Mídia em disco não é confiável — o vídeo será baixado de novo"
        )
        return None
    return VideoMetadata(
        title=saved["video_title"] or "Unknown Title",
        channel=saved["channel_name"] or "Unknown Channel",
        duration=saved["duration_seconds"] or 0.0,
        thumbnail_url=saved["thumbnail_url"],
        video_path=video_path,
        audio_path=audio_path,
    )


async def _discard_derived_work(job_id: str) -> None:
    """
    Joga fora tudo que foi derivado do vídeo antigo: transcrição, análise e
    clips renderizados.

    Chamado quando o vídeo vai ser baixado de novo. Os timestamps da
    transcrição valem para o áudio que a gerou; contra um arquivo novo eles
    apontam para outro momento do vídeo. Apagar é o que força o resume a
    refazer transcrição e análise em cima da mídia nova.
    """
    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(Transcript).where(Transcript.job_id == job_id)
        )
        for transcript in result.scalars().all():
            if transcript.words_json_path:
                Path(transcript.words_json_path).unlink(missing_ok=True)
        await db.execute(delete(Transcript).where(Transcript.job_id == job_id))
        await db.execute(delete(Clip).where(Clip.job_id == job_id))
        await db.commit()

    shutil.rmtree(settings.clips_dir / job_id, ignore_errors=True)
    logger.info(f"[{job_id}] Transcrição, análise e clips antigos descartados")


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
            segments=_parse_segments_json(clip.segments_json),
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
                hook_score=vc.hook_score,
                retention_score=vc.retention_score,
                shareability_score=vc.shareability_score,
                loopability_score=vc.loopability_score,
                comment_bait_score=vc.comment_bait_score,
                verdict=vc.verdict,
                weak_points_json=json.dumps(vc.weak_points),
                trim_reason=vc.trim_reason,
                segments_json=json.dumps(vc.segments) if vc.segments else None,
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
                    segments=list(vc.segments),
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
) -> tuple[list[CamPhase], str | None]:
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

    Returns:
        (fases, json da caixa dominante) — o JSON só vem preenchido quando
        store=True, para o chamador usar como referência de tamanho nos clipes
        seguintes DESTA execução. Sem isso a referência só existiria depois de
        um resume. Ela NÃO é imposta às fases — serve à UI e ao usuário.
    """
    duration = end_time - start_time

    manual = _manual_rect(facecam_json)
    if manual:
        logger.info(f"[{job_id}] Facecam: using rect from job ({manual.method})")
        return single_phase(manual, duration), None

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

    # A caixa gravada no job NÃO é mais imposta às fases. Ela existia como
    # referência de tamanho entre clipes, mas a referência é ela própria uma
    # detecção — e quando ERRA, o erro passa a ser forçado por cima de todas as
    # detecções boas dos clipes seguintes. Foi o que aconteceu no vídeo do
    # Bahiaqz: uma execução gravou o card "RELATÓRIO" do jogo (40% x 44% do
    # frame) e, a partir daí, todo clipe do job renderizou o painel do rosto
    # mostrando o card, inclusive os que tinham detectado a cam certa.
    #
    # A consistência que ela tentava garantir agora é feita DENTRO de cada
    # clipe (facecam._absorb_size_outliers), onde a referência é a própria cam
    # daquele trecho e não um palpite herdado.

    if store:
        dominant = max(phases, key=lambda p: p.end - p.start).rect
        stored = json.dumps(dominant.as_dict())
        await _update_job_status(job_id, "clipping", facecam_rect=stored)
        return phases, stored
    return phases, None


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
    # um reload durante o trabalho marcaria o job como interrompido. E é
    # exclusivo: dois pipelines no mesmo job corrompem os arquivos um do outro.
    try:
        with joblock.held(job_id):
            await _execute_pipeline(job_id, resume)
    except joblock.JobAlreadyRunning as exc:
        # Quem já está trabalhando segue em frente; este processo sai sem tocar
        # em nada — nem no status do job, que pertence ao outro.
        logger.warning(f"[{job_id}] {exc} — este processo não vai duplicar o trabalho")


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
            source_type = job.source_type or default_source_type(layout_mode)
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
        metadata = await _media_from_job(job_id, saved_media) if resume else None
        if metadata:
            logger.info(f"[{job_id}] Resume: vídeo e áudio em disco — download pulado")
        else:
            if resume:
                # Baixar de novo troca o arquivo sob os pés da transcrição e da
                # análise, que descrevem a linha do tempo do áudio anterior.
                # Reaproveitá-las deslocaria todos os cortes.
                await _discard_derived_work(job_id)
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

            # O que a transcrição não conta: onde os buracos sem fala são a
            # gargalhada ou a jogada, e não tempo morto. Sem isto a análise lê
            # o melhor momento do vídeo como ausência de conteúdo.
            gaps = await detect_gaps(job_id, metadata.audio_path, words)

            # E o que a tela mostrava nesses momentos. O áudio diz quando; a
            # imagem diz o quê — e só olha as janelas que o áudio apontou.
            await describe_events(job_id, metadata.video_path, gaps)

            analysis = await analyze_virality(
                job_id=job_id,
                words=words,
                title=metadata.title,
                channel=metadata.channel,
                duration_seconds=metadata.duration,
                source_type=source_type,
                gaps=gaps,
                video_path=metadata.video_path,
            )

            logger.info(
                f"[{job_id}] Analysis complete: {len(analysis.clips)} clips to generate"
            )

            if not analysis.clips:
                await _update_job_status(job_id, "done")
                logger.info(f"[{job_id}] No viral clips found. Pipeline complete.")
                return

            # Em Siege a fala não conta a jogada, e a análise por texto já
            # escolheu 52s do streamer MORTO comentando uma troca que nem
            # aparece. O HUD do jogo diz quem está vivo — é barato conferir os
            # candidatos antes de gastar render neles.
            if source_type == "siege":
                analysis.clips = await _drop_dead_candidates(
                    job_id, metadata.video_path, analysis.clips
                )
                if not analysis.clips:
                    await _update_job_status(job_id, "done")
                    logger.info(
                        f"[{job_id}] Todos os candidatos eram com o streamer morto."
                    )
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
            compacted: str | None = None
            try:
                # Clip costurado (Siege): os trechos viram um arquivo só, e o
                # render trabalha nele como se fosse um vídeo comum. É o que
                # mantém facecam, faixa, banner e legendas sem mexer no
                # filtergraph — ele nunca sabe que houve emenda.
                source_path = metadata.video_path
                clip_start, clip_end = task.start, task.end
                clip_words = words
                if task.segments:
                    compacted = str(
                        settings.clips_dir / job_id / f"{task.clip_id}_costurado.mp4"
                    )
                    Path(compacted).parent.mkdir(parents=True, exist_ok=True)
                    total = await compact_segments(
                        job_id, task.clip_id, metadata.video_path,
                        task.segments, compacted,
                    )
                    source_path = compacted
                    clip_start, clip_end = 0.0, total
                    clip_words = remap_words(words, task.segments)

                if layout_mode == "streamer":
                    # O layout da live muda ao longo do vídeo: cada clip tem a
                    # sua própria linha do tempo de facecam.
                    facecam, stored_rect = await _resolve_facecam(
                        job_id=job_id,
                        video_path=source_path,
                        facecam_json=facecam_json,
                        start_time=clip_start,
                        end_time=clip_end,
                        store=index == 0,
                    )
                    # Sem isto a caixa do 1º clip ia só para o banco, e os
                    # clipes seguintes desta execução ficariam sem referência
                    # de tamanho — era assim que um encaixe inflado passava e
                    # trazia gameplay para dentro do painel do rosto.
                    if stored_rect:
                        facecam_json = stored_rect
                    file_path, file_size = await cut_and_stack(
                        job_id=job_id,
                        clip_id=task.clip_id,
                        video_path=source_path,
                        start_time=clip_start,
                        end_time=clip_end,
                        words=clip_words,
                        subtitle_mode=subtitle_mode,
                        facecam=facecam,
                        streamer_name=metadata.channel,
                        source_type=source_type,
                    )
                else:
                    file_path, file_size = await cut_and_crop(
                        job_id=job_id,
                        clip_id=task.clip_id,
                        video_path=source_path,
                        start_time=clip_start,
                        end_time=clip_end,
                        words=clip_words,
                        subtitle_mode=subtitle_mode,
                        banner_text=task.banner_text,
                        source_type=source_type,
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

            finally:
                # O intermediário da costura é um 4K de ~1 min: deixar para trás
                # enche o disco em poucos jobs. Sai mesmo se o render falhou.
                segments_service.cleanup(compacted)

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
