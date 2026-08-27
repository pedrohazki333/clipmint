import json
import logging
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.database import get_db
from app.deps import current_user, owned_by
from app.features import learning_enabled
from app.models import Clip, Job, Transcript, User
from app.schemas import (
    ClipMetricsRequest,
    ClipResponse,
    ValidateClipRequest,
    ValidateClipResponse,
)

logger = logging.getLogger(__name__)

router = APIRouter(tags=["clips"])


async def _clip_do_usuario(
    clip_id: str, user: User, db: AsyncSession, carregar_job: bool = False
) -> Clip:
    """
    O clip, se o job dele for desta pessoa. 404 se não for.

    O clip não guarda dono — quem guarda é o job. Sem esta junção, um id de clip
    adivinhado daria acesso ao vídeo de outra pessoa: o /download entrega o
    arquivo, e ele é o produto inteiro.

    404 e não 403: um 403 confirmaria que o clip existe.
    """
    consulta = select(Clip).join(Job, Clip.job_id == Job.id).where(
        Clip.id == clip_id, owned_by(user)
    )
    if carregar_job:
        consulta = consulta.options(selectinload(Clip.job).selectinload(Job.transcript))
    clip = (await db.execute(consulta)).scalar_one_or_none()
    if not clip:
        raise HTTPException(status_code=404, detail="Clip not found")
    return clip


# Diretório onde os exemplos validados são salvos
_VALIDATED_DIR = Path(__file__).parent.parent.parent / "prompt_engine" / "examples" / "validated"


def _extract_opening_phrase(words: list[dict], start_time: float, max_words: int = 12) -> str:
    """
    Extrai a frase de abertura do clip a partir do JSON de palavras.

    Pega as primeiras `max_words` palavras a partir de `start_time`,
    parando também no primeiro fim de frase completa encontrado.
    """
    clip_words = [w for w in words if w.get("start", 0) >= start_time]
    selected: list[str] = []

    for word in clip_words[:max_words]:
        text = word.get("text", "")
        selected.append(text)
        if text.rstrip().endswith((".", "!", "?", "...")):
            break

    return " ".join(selected).strip()


@router.post("/clips/{clip_id}/validate", response_model=ValidateClipResponse, status_code=201)
async def validate_clip(
    clip_id: str,
    payload: ValidateClipRequest,
    user: User = Depends(current_user),
    db: AsyncSession = Depends(get_db),
) -> ValidateClipResponse:
    """
    Salva um clip como exemplo validado para few-shot learning.

    Busca os dados do clip, do job e da transcrição no banco,
    monta o JSON de exemplo completo e persiste em
    prompt_engine/examples/validated/example_{clip_id}.json.
    """
    # O exemplo validado vai para uma pasta ÚNICA, que o PromptBuilder injeta na
    # análise de todo mundo — então no build público isto ficaria misturando o
    # aprendizado de um usuário com o corte dos outros. A rota existe, mas
    # responde 404 lá: o mesmo que ela não existir, sem precisar partir o router
    # de clips em dois (o resto dele é público).
    if not learning_enabled():
        raise HTTPException(status_code=404, detail="Not Found")

    # ── 1. Carrega o clip com job e transcript via join ───────────────────────
    clip = await _clip_do_usuario(clip_id, user, db, carregar_job=True)

    if clip.status != "ready":
        raise HTTPException(
            status_code=400,
            detail="Only clips with status 'ready' can be validated.",
        )

    job: Job = clip.job
    transcript: Transcript | None = job.transcript

    # ── 2. Extrai frase de abertura do words JSON ──────────────────────────────
    opening_phrase = ""
    if transcript and transcript.words_json_path:
        words_path = Path(transcript.words_json_path)
        if words_path.exists():
            try:
                words: list[dict] = json.loads(words_path.read_text(encoding="utf-8"))
                opening_phrase = _extract_opening_phrase(words, clip.start_time)
            except (json.JSONDecodeError, OSError) as e:
                logger.warning(f"[{clip_id}] Could not read words JSON for opening phrase: {e}")

    # ── 3. Parseia tags salvas no banco ───────────────────────────────────────
    tags: list[str] = []
    if clip.tags_json:
        try:
            tags = json.loads(clip.tags_json)
        except json.JSONDecodeError:
            pass

    # ── 4. Monta o JSON de exemplo ────────────────────────────────────────────
    example: dict = {
        "clip_id": clip.id,
        "validated_at": datetime.now(timezone.utc).isoformat(),
        "video": {
            "url": job.youtube_url,
            "title": job.video_title or "",
            "channel": job.channel_name or "",
            "language": transcript.language if transcript else "",
            "duration": job.duration_seconds or 0,
        },
        "clip": {
            "start": clip.start_time,
            "end": clip.end_time,
            "duration": clip.duration,
            "opening_phrase": opening_phrase,
            "virality_score": clip.virality_score,
            "hook": clip.hook or "",
            "suggested_title": clip.suggested_title or "",
            "reason": clip.reason or "",
            "tags": tags,
        },
        "validation": {
            "performance": payload.performance,
            "aprendizado": payload.aprendizado.strip(),
            "views": payload.views,
        },
    }

    # ── 5. Persiste o arquivo JSON ────────────────────────────────────────────
    _VALIDATED_DIR.mkdir(parents=True, exist_ok=True)
    output_path = _VALIDATED_DIR / f"example_{clip.id}.json"
    output_path.write_text(json.dumps(example, ensure_ascii=False, indent=2), encoding="utf-8")

    logger.info(f"[{clip_id}] Validated example saved to {output_path}")

    return ValidateClipResponse(
        example_path=str(output_path),
        clip_id=clip.id,
    )


@router.get("/clips/{clip_id}", response_model=ClipResponse)
async def get_clip(
    clip_id: str,
    user: User = Depends(current_user),
    db: AsyncSession = Depends(get_db),
) -> Clip:
    """Retorna detalhes de um clip específico."""
    return await _clip_do_usuario(clip_id, user, db)


@router.put("/clips/{clip_id}/metrics", response_model=ClipResponse)
async def set_clip_metrics(
    clip_id: str,
    payload: ClipMetricsRequest,
    user: User = Depends(current_user),
    db: AsyncSession = Depends(get_db),
) -> Clip:
    """
    Registra o desempenho real de um clipe já postado.

    A nota de viralidade é uma previsão feita antes de o clipe existir; estes
    números são o que aconteceu depois. Eles são a única forma de o sistema
    descobrir que um clipe de nota alta rendeu mal — nenhuma análise de texto,
    áudio ou imagem consegue saber isso sozinha.

    A atualização é parcial: os campos ausentes ficam como estavam, então dá
    para lançar as views hoje e a retenção quando ela aparecer no painel.
    `metrics_at` é carimbado a cada chamada, porque views sem data de coleta
    não são comparáveis entre clipes de idades diferentes.
    """
    clip = await _clip_do_usuario(clip_id, user, db)

    changed = payload.model_dump(exclude_none=True)
    if not changed:
        raise HTTPException(
            status_code=400,
            detail="Informe ao menos uma métrica (views, completion_rate, likes, comments, shares ou posted_at).",
        )

    for field, value in changed.items():
        setattr(clip, field, value)
    clip.metrics_at = datetime.now(timezone.utc)

    await db.commit()
    await db.refresh(clip)

    logger.info(f"Clip {clip_id}: métricas registradas ({', '.join(changed)})")
    return clip


@router.get("/clips/{clip_id}/download")
async def download_clip(
    clip_id: str,
    user: User = Depends(current_user),
    db: AsyncSession = Depends(get_db),
) -> FileResponse:
    """Faz download do arquivo de vídeo do clip."""
    clip = await _clip_do_usuario(clip_id, user, db)
    if clip.status != "ready" or not clip.file_path:
        raise HTTPException(status_code=400, detail="Clip is not ready for download")

    file_path = Path(clip.file_path)
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="Clip file not found on disk")

    filename = file_path.name
    return FileResponse(
        path=str(file_path),
        media_type="video/mp4",
        filename=filename,
    )
