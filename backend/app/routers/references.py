"""
Router de referências — aprender a cortar a partir de um clipe viral de outro criador.

Há duas portas de entrada, e a diferença entre elas é o que se tem em mãos:

  POST /references             URL do vídeo ORIGINAL + o clipe viral. O pipeline
                               localiza o corte dentro do original e explica por
                               que foi ali.
  POST /references/standalone  Só o clipe (o caso do TikTok, em que o original é
                               desconhecido). O clipe é periciado por si: fala,
                               som, imagem e cortes.

Daí em diante o fluxo é o mesmo para os dois:
  2. GET /references/{id}  → acompanha status e vê a análise gerada.
  3. PATCH /references/{id}  → ajusta o intervalo localizado / performance / notas
       (opcionalmente re-roda a análise reversa com o novo intervalo).
  4. POST /references/{id}/confirm  → publica como exemplo few-shot validado,
       entrando automaticamente no PromptBuilder.
"""

import json
import logging
import shutil
import tempfile

import anthropic
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import get_db
from app.features import source_type_allowed
from app.models import ReferenceExample
from app.schemas import ReferenceConfirmResponse, ReferenceResponse, ReferenceUpdateRequest
from app.services.reference_analyzer import analyze_reference
from app.workers.reference_pipeline import (
    _opening_phrase,
    run_reference_pipeline,
    run_standalone_pipeline,
)
from app.schemas import _YOUTUBE_URL_RE  # reutiliza o validador de URL do YouTube
from prompt_engine.pattern_miner import (
    clear_learned,
    load_learned,
    load_validated_examples,
    mine_and_write,
)

logger = logging.getLogger(__name__)

router = APIRouter(tags=["references"])

_VALIDATED_DIR = Path(__file__).parent.parent.parent / "prompt_engine" / "examples" / "validated"
_ALLOWED_CLIP_EXT = {".mp4", ".mov", ".mkv", ".webm", ".avi", ".m4v"}
_MAX_CLIP_BYTES = 500 * 1024 * 1024  # 500MB


def _valid_source_type(value: str) -> str:
    """Nicho informado, ou 'podcast' quando vier algo que não existe.

    A lista permitida depende do build (ver app/features.py): no público, uma
    referência marcada como "siege" cai no default em vez de criar um nicho
    que a interface não tem como mostrar.
    """
    value = (value or "").strip().lower()
    return value if source_type_allowed(value) else "podcast"


def _load_json(raw: Optional[str]) -> Optional[dict]:
    """Parseia uma coluna JSON, devolvendo None quando ela não é aproveitável."""
    if not raw:
        return None
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return None


def _to_response(ref: ReferenceExample) -> ReferenceResponse:
    """Monta o ReferenceResponse parseando as colunas JSON."""
    return ReferenceResponse(
        id=ref.id,
        kind=ref.kind or "aligned",
        source_type=ref.source_type or "podcast",
        source_url=ref.source_url,
        source_title=ref.source_title,
        source_channel=ref.source_channel,
        source_duration=ref.source_duration,
        language=ref.language,
        source_start=ref.source_start,
        source_end=ref.source_end,
        alignment_confidence=ref.alignment_confidence,
        clip_duration=ref.clip_duration,
        analysis=_load_json(ref.analysis_json),
        forensics=_load_json(ref.forensics_json),
        opening_phrase=ref.opening_phrase,
        transcript_excerpt=ref.transcript_excerpt,
        performance=ref.performance,
        views=ref.views,
        notas=ref.notas,
        status=ref.status,
        error_message=ref.error_message,
        published=bool(ref.published),
        example_path=ref.example_path,
        created_at=ref.created_at,
        updated_at=ref.updated_at,
    )


async def _get_or_404(reference_id: str, db: AsyncSession) -> ReferenceExample:
    result = await db.execute(
        select(ReferenceExample).where(ReferenceExample.id == reference_id)
    )
    ref = result.scalar_one_or_none()
    if not ref:
        raise HTTPException(status_code=404, detail="Referência não encontrada")
    return ref


#: Tamanho do pedaço lido por vez. 1MB é grande o bastante para o custo por
#: pedaço ser irrelevante e pequeno o bastante para o pico de memória não pesar.
_CHUNK = 1024 * 1024


async def _stage_clip(clip: UploadFile) -> tuple[Path, str]:
    """
    Valida o upload e o grava num arquivo temporário. Devolve (caminho, extensão).

    Em pedaços, e não com um `await clip.read()` de uma vez. Aquela versão
    carregava o arquivo INTEIRO na memória do processo e só DEPOIS comparava
    com o teto de 500MB — ou seja, o teto não protegia de nada: um upload de
    2GB já tinha sido lido antes de ser recusado. Num VPS pequeno com mais de
    um usuário, é o caminho mais curto para o OOM.
    """
    ext = Path(clip.filename or "").suffix.lower()
    if ext not in _ALLOWED_CLIP_EXT:
        raise HTTPException(
            status_code=422,
            detail=f"Formato de clipe inválido ({ext or 'sem extensão'}). Aceitos: {', '.join(sorted(_ALLOWED_CLIP_EXT))}",
        )

    settings.references_dir.mkdir(parents=True, exist_ok=True)
    handle = tempfile.NamedTemporaryFile(
        dir=settings.references_dir, suffix=ext, delete=False
    )
    staged = Path(handle.name)
    total = 0
    try:
        with handle:
            while pedaco := await clip.read(_CHUNK):
                total += len(pedaco)
                if total > _MAX_CLIP_BYTES:
                    # Aborta no pedaço em que o limite estoura: o resto do
                    # corpo nem chega a ser lido nem gravado.
                    raise HTTPException(
                        status_code=413, detail="Clipe muito grande (máx. 500MB)"
                    )
                handle.write(pedaco)
        if not total:
            raise HTTPException(status_code=422, detail="Arquivo de clipe vazio")
    except BaseException:
        staged.unlink(missing_ok=True)
        raise

    return staged, ext


async def _persist_clip(
    db: AsyncSession, ref: ReferenceExample, staged: Path, ext: str
) -> None:
    """
    Grava a linha e move o arquivo já recebido para o nome definitivo.

    O registro é criado antes do arquivo porque é o ID dele que nomeia o
    arquivo — e é esse mesmo ID que o DELETE usa depois para achar tudo que
    ficou no storage. O upload já está em disco (ver _stage_clip), então aqui é
    só um rename dentro do mesmo diretório: não passa pela memória.
    """
    try:
        db.add(ref)
        await db.commit()
        await db.refresh(ref)

        clip_path = settings.references_dir / f"{ref.id}_clip{ext}"
        staged.replace(clip_path)

        ref.clip_path = str(clip_path)
        await db.commit()
        await db.refresh(ref)
    except BaseException:
        staged.unlink(missing_ok=True)  # não deixa temporário para trás
        raise


@router.post("/references", response_model=ReferenceResponse, status_code=201)
async def create_reference(
    background_tasks: BackgroundTasks,
    source_url: str = Form(...),
    clip: UploadFile = File(...),
    source_type: str = Form("podcast"),
    db: AsyncSession = Depends(get_db),
) -> ReferenceResponse:
    """Cria uma referência (URL do original + clipe viral) e inicia o pipeline."""
    source_url = source_url.strip()
    if not _YOUTUBE_URL_RE.match(source_url):
        raise HTTPException(
            status_code=422,
            detail="URL inválida: forneça o link do YouTube do vídeo ORIGINAL (youtube.com ou youtu.be)",
        )

    staged, ext = await _stage_clip(clip)

    ref = ReferenceExample(
        kind="aligned",
        source_url=source_url,
        source_type=_valid_source_type(source_type),
        clip_path="",
        status="queued",
    )
    await _persist_clip(db, ref, staged, ext)

    logger.info(f"Reference {ref.id} created (source={source_url}, clip={ref.clip_path})")
    background_tasks.add_task(run_reference_pipeline, ref.id)

    return _to_response(ref)


@router.post("/references/standalone", response_model=ReferenceResponse, status_code=201)
async def create_standalone_reference(
    background_tasks: BackgroundTasks,
    clip: UploadFile = File(...),
    title: str = Form(""),
    channel: str = Form(""),
    post_url: str = Form(""),
    source_type: str = Form("podcast"),
    notas: str = Form(""),
    db: AsyncSession = Depends(get_db),
) -> ReferenceResponse:
    """
    Cria uma referência a partir SÓ do arquivo do clipe e inicia a perícia.

    É o caminho para um clipe salvo do TikTok, que não diz de onde saiu. Nada
    além do arquivo é obrigatório: título, criador e link do post entram na
    análise como contexto quando o usuário souber, e a ausência deles não impede
    nada — a perícia se sustenta no que está dentro do arquivo.

    `notas` vale a pena preencher: o que o usuário já percebeu sobre o clipe vai
    junto no prompt da síntese, e vira o "aprendizado" do exemplo few-shot.
    """
    staged, ext = await _stage_clip(clip)

    ref = ReferenceExample(
        kind="standalone",
        # Sem original: a coluna guarda o link do post, quando houver.
        source_url=post_url.strip(),
        source_title=title.strip() or (clip.filename or "").strip() or None,
        source_channel=channel.strip() or None,
        source_type=_valid_source_type(source_type),
        notas=notas.strip() or None,
        clip_path="",
        status="queued",
    )
    await _persist_clip(db, ref, staged, ext)

    logger.info(f"Standalone reference {ref.id} created (clip={ref.clip_path})")
    background_tasks.add_task(run_standalone_pipeline, ref.id)

    return _to_response(ref)


@router.get("/references", response_model=list[ReferenceResponse])
async def list_references(db: AsyncSession = Depends(get_db)) -> list[ReferenceResponse]:
    """Lista todas as referências em ordem decrescente de criação."""
    result = await db.execute(
        select(ReferenceExample).order_by(ReferenceExample.created_at.desc())
    )
    return [_to_response(r) for r in result.scalars().all()]


@router.get("/references/{reference_id}", response_model=ReferenceResponse)
async def get_reference(
    reference_id: str, db: AsyncSession = Depends(get_db)
) -> ReferenceResponse:
    """Detalhes de uma referência, incluindo a análise reversa gerada."""
    ref = await _get_or_404(reference_id, db)
    return _to_response(ref)


@router.patch("/references/{reference_id}", response_model=ReferenceResponse)
async def update_reference(
    reference_id: str,
    payload: ReferenceUpdateRequest,
    db: AsyncSession = Depends(get_db),
) -> ReferenceResponse:
    """
    Ajusta o intervalo localizado, a performance real, views e notas.

    Se `reanalyze=True` e o intervalo mudar, re-roda a análise reversa do Claude
    com o novo trecho (recarrega as palavras do original do disco).
    """
    ref = await _get_or_404(reference_id, db)

    # No modo standalone o clipe É o corte: não existe original dentro do qual
    # relocalizá-lo, e mexer no intervalo só corromperia o exemplo publicado
    # (que grava start/end como os limites do clipe).
    if ref.kind == "standalone" and (
        payload.source_start is not None
        or payload.source_end is not None
        or payload.reanalyze
    ):
        raise HTTPException(
            status_code=409,
            detail=(
                "Esta referência não tem vídeo de origem: o clipe inteiro já é o corte. "
                "Não há intervalo a ajustar nem reanálise por intervalo."
            ),
        )

    span_changed = False
    if payload.source_start is not None and payload.source_start != ref.source_start:
        ref.source_start = payload.source_start
        span_changed = True
    if payload.source_end is not None and payload.source_end != ref.source_end:
        ref.source_end = payload.source_end
        span_changed = True

    if ref.source_start is not None and ref.source_end is not None:
        if ref.source_end <= ref.source_start:
            raise HTTPException(status_code=422, detail="source_end deve ser maior que source_start")
        ref.clip_duration = ref.source_end - ref.source_start

    if payload.performance is not None:
        ref.performance = payload.performance
    if payload.views is not None:
        ref.views = payload.views
    if payload.notas is not None:
        ref.notas = payload.notas

    if payload.reanalyze and span_changed:
        words_path = settings.transcripts_dir / f"{reference_id}_src_words.json"
        if not words_path.exists():
            raise HTTPException(
                status_code=409,
                detail="Transcrição do vídeo original indisponível para reanálise",
            )
        source_words = json.loads(words_path.read_text(encoding="utf-8"))
        analysis = await analyze_reference(
            reference_id=reference_id,
            source_words=source_words,
            source_start=ref.source_start,
            source_end=ref.source_end,
            title=ref.source_title or "",
            channel=ref.source_channel or "",
            language=ref.language or "",
        )
        ref.analysis_json = json.dumps(asdict(analysis), ensure_ascii=False)
        ref.opening_phrase = _opening_phrase(source_words, ref.source_start)
        excerpt_words = [
            w["text"] for w in source_words
            if w["start"] >= ref.source_start and w["end"] <= ref.source_end
        ]
        ref.transcript_excerpt = " ".join(excerpt_words[:60])

    ref.updated_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(ref)
    return _to_response(ref)


@router.post("/references/{reference_id}/confirm", response_model=ReferenceConfirmResponse, status_code=201)
async def confirm_reference(
    reference_id: str, db: AsyncSession = Depends(get_db)
) -> ReferenceConfirmResponse:
    """
    Publica a referência como exemplo few-shot validado.

    Grava o JSON em prompt_engine/examples/validated/ no mesmo schema dos clipes
    validados (com source="external_reference"), de onde o PromptBuilder o injeta
    automaticamente nas próximas análises.
    """
    ref = await _get_or_404(reference_id, db)

    if ref.status != "done":
        raise HTTPException(
            status_code=400,
            detail=f"Referência ainda não está pronta (status: {ref.status})",
        )
    if ref.source_start is None or ref.source_end is None:
        raise HTTPException(status_code=400, detail="Intervalo do clipe não localizado")

    analysis: dict = {}
    if ref.analysis_json:
        try:
            analysis = json.loads(ref.analysis_json)
        except json.JSONDecodeError:
            analysis = {}

    # "aprendizado" alimenta o few-shot como "por que funcionou": preferimos a nota
    # do usuário; senão, a explicação do corte gerada pela IA.
    aprendizado = (ref.notas or "").strip() or analysis.get("why_this_cut", "") or analysis.get("reason", "")

    example = {
        "clip_id": ref.id,
        # Rótulos distintos porque as duas fontes ensinam coisas diferentes: uma
        # sabe o que foi deixado de fora, a outra não. O pattern_miner conta as
        # fontes separadamente por isso.
        "source": "external_clip" if ref.kind == "standalone" else "external_reference",
        "source_type": ref.source_type or "podcast",
        "validated_at": datetime.now(timezone.utc).isoformat(),
        "video": {
            "url": ref.source_url,
            "title": ref.source_title or "",
            "channel": ref.source_channel or "",
            "language": ref.language or "",
            # No standalone fica 0 de propósito: `source_duration` é a duração
            # do vídeo ORIGINAL, e aqui não há original. O pattern_miner ignora
            # duração 0 ao calcular a posição do corte no vídeo — se em vez
            # disso puséssemos a duração do clipe, todo exemplo standalone
            # entraria como "corte no início do vídeo", que é uma estatística
            # inventada sobre um vídeo que ninguém viu.
            "duration": ref.source_duration or 0,
        },
        "clip": {
            "start": ref.source_start,
            "end": ref.source_end,
            "duration": ref.clip_duration or (ref.source_end - ref.source_start),
            "opening_phrase": ref.opening_phrase or "",
            "virality_score": analysis.get("virality_score", 0),
            "hook": analysis.get("hook", ""),
            "suggested_title": analysis.get("suggested_title", ""),
            "reason": analysis.get("reason", ""),
            "tags": analysis.get("tags", []),
        },
        "validation": {
            "performance": ref.performance or "bom",
            "aprendizado": aprendizado,
            "views": ref.views,
        },
    }

    # A perícia entra no exemplo para o PromptBuilder poder mostrar COMO o clipe
    # funciona, não só que ele funcionou.
    forensics = _load_json(ref.forensics_json)
    if forensics:
        example["forensics"] = forensics

    _VALIDATED_DIR.mkdir(parents=True, exist_ok=True)
    prefix = "example_clip" if ref.kind == "standalone" else "example_ref"
    output_path = _VALIDATED_DIR / f"{prefix}_{ref.id}.json"
    output_path.write_text(json.dumps(example, ensure_ascii=False, indent=2), encoding="utf-8")

    ref.published = 1
    ref.example_path = str(output_path)
    ref.updated_at = datetime.now(timezone.utc)
    await db.commit()

    logger.info(f"[{reference_id}] Published as validated example → {output_path}")
    return ReferenceConfirmResponse(reference_id=ref.id, example_path=str(output_path))


@router.get("/patterns")
async def get_patterns() -> dict:
    """
    Retorna os padrões aprendidos atuais + quantos exemplos validados existem hoje.

    `stale` indica que há mais exemplos do que os usados na última mineração,
    sugerindo recalcular.
    """
    available = len(load_validated_examples())
    learned = load_learned()
    if not learned:
        return {
            "patterns": [],
            "patterns_text": "",
            "generated_at": None,
            "n_examples": 0,
            "available_examples": available,
            "stats": None,
            "stale": available > 0,
        }
    return {
        "patterns": learned.get("patterns", []),
        "patterns_text": learned.get("patterns_text", ""),
        "generated_at": learned.get("generated_at"),
        "n_examples": learned.get("n_examples", 0),
        "available_examples": available,
        "stats": learned.get("stats"),
        "stale": available != learned.get("n_examples", 0),
    }


@router.post("/patterns/mine")
async def mine_patterns() -> dict:
    """Recalcula os padrões aprendidos a partir de todos os exemplos validados."""
    examples = load_validated_examples()
    if not examples:
        raise HTTPException(
            status_code=400,
            detail="Nenhum exemplo validado ainda. Confirme ao menos uma referência ou clipe antes de minerar padrões.",
        )
    try:
        result = await mine_and_write(examples)
    except anthropic.AuthenticationError:
        raise HTTPException(
            status_code=502,
            detail="Chave da API do Claude inválida. Verifique ANTHROPIC_API_KEY no .env.",
        )
    except anthropic.APIError as e:
        raise HTTPException(status_code=502, detail=f"Falha na API do Claude: {e}")
    result["available_examples"] = len(examples)
    result["stale"] = False
    return result


@router.delete("/patterns", status_code=204)
async def delete_patterns() -> None:
    """Remove os padrões aprendidos (volta a usar só core + few-shot)."""
    clear_learned()


@router.delete("/references/{reference_id}", status_code=204)
async def delete_reference(
    reference_id: str, db: AsyncSession = Depends(get_db)
) -> None:
    """Exclui a referência e seus arquivos (clipe, download do original, transcrições, exemplo publicado)."""
    ref = await _get_or_404(reference_id, db)
    published_path = ref.example_path
    clip_path = ref.clip_path
    await db.delete(ref)
    await db.commit()

    # Arquivos no storage (caminhos derivados do ID)
    if clip_path:
        Path(clip_path).unlink(missing_ok=True)
    (settings.references_dir / f"{reference_id}_clip.wav").unlink(missing_ok=True)
    shutil.rmtree(settings.downloads_dir / reference_id, ignore_errors=True)
    (settings.transcripts_dir / f"{reference_id}_src_words.json").unlink(missing_ok=True)
    (settings.transcripts_dir / f"{reference_id}_clip_words.json").unlink(missing_ok=True)
    if published_path:
        Path(published_path).unlink(missing_ok=True)

    logger.info(f"Reference {reference_id} deleted (records + storage)")
