"""
Testes da perícia de um clipe viral que chegou sem o vídeo de origem.

O que está coberto aqui são as funções puras — onde a amostragem de quadros
cai, o que a curva de loudness vira, e como a leitura da visão é ancorada no
tempo. As chamadas de API e o ffmpeg ficam de fora de propósito: o que quebra
em silêncio neste módulo não é a rede, é um índice fora de lugar transformando
uma observação num fato sobre o instante errado.

Sem pytest-asyncio no projeto, corrotina roda com asyncio.run (mesma convenção
de test_audio_events.py).
"""

import asyncio
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.database import Base, get_db
from app.main import app
from app.models import ReferenceExample
from app.services.clip_forensics import (
    ClipEvidence,
    Frame,
    FrameNote,
    VisualReadout,
    build_readout,
    frame_times,
    parse_cut_times,
    summarize_loudness,
    timed_transcript,
)
from prompt_engine.prompt_builder import PromptBuilder


def _word(text, start, end):
    return {"text": text, "start": start, "end": end, "confidence": 0.9}


# ─── Amostragem de quadros ────────────────────────────────────────────────────

def test_hook_is_sampled_denser_than_the_rest():
    """
    O gancho recebe amostras próprias.

    Numa grade uniforme de 14 quadros em 40s o primeiro intervalo teria ~3s, e o
    overlay do gancho — que costuma sair da tela antes disso — não apareceria em
    quadro nenhum. Esse é o modo de falha que a amostragem densa existe para
    evitar, então ele é testado pelo espaçamento, não pela lista literal.
    """
    times = frame_times(40.0, count=14, hook_seconds=3.0)

    no_gancho = [t for t in times if t < 3.0]
    assert len(no_gancho) >= 3
    assert max(b - a for a, b in zip(no_gancho, no_gancho[1:])) < 1.0

    depois = [t for t in times if t >= 3.0]
    assert min(b - a for a, b in zip(depois, depois[1:])) > 1.0


def test_frames_never_land_on_the_very_last_instant():
    """Pedir exatamente a duração devolve arquivo vazio em muitos containers."""
    times = frame_times(40.0, count=14)
    assert times[-1] < 40.0
    assert times[-1] > 39.0  # mas o fim ainda é coberto


def test_frame_count_is_respected():
    assert len(frame_times(40.0, count=14)) == 14
    assert len(frame_times(40.0, count=6)) == 6
    assert len(frame_times(1.5, count=8)) == 8


def test_clip_shorter_than_the_hook_window_is_sampled_uniformly():
    """Sem 'resto' para amostrar, a grade uniforme cobre o clipe inteiro."""
    times = frame_times(2.0, count=5, hook_seconds=3.0)
    gaps = [b - a for a, b in zip(times, times[1:])]
    assert all(g == pytest.approx(gaps[0], abs=0.002) for g in gaps)


def test_degenerate_inputs_return_nothing():
    assert frame_times(0.0) == []
    assert frame_times(-5.0) == []
    assert frame_times(30.0, count=0) == []
    assert frame_times(30.0, count=1) == [0.0]


# ─── Transcrição com tempo ────────────────────────────────────────────────────

def test_transcript_breaks_by_time_not_by_word_count():
    """
    A quebra é por tempo porque o que se quer ver é o ritmo.

    Aqui há uma rajada de quatro palavras em meio segundo e depois uma pausa: as
    quatro precisam ficar na mesma linha, e o que vem depois da pausa, em outra.
    """
    words = [
        _word("cara", 0.0, 0.2), _word("olha", 0.2, 0.4),
        _word("isso", 0.4, 0.5), _word("aqui", 0.5, 0.6),
        _word("inacreditável", 5.0, 5.8),
    ]
    linhas = timed_transcript(words, seconds_per_line=3.0).split("\n")

    assert linhas == ["[0.0s] cara olha isso aqui", "[5.0s] inacreditável"]


def test_transcript_without_words_says_so():
    assert timed_transcript([]) == "(sem fala transcrita)"


# ─── Curva de som ─────────────────────────────────────────────────────────────

def _timeline(pairs):
    """Expande (início, fim, valor) em amostras a cada 100ms, como o ebur128."""
    out = []
    for start, end, value in pairs:
        t = start
        while t < end - 1e-9:
            out.append((round(t, 1), value))
            t += 0.1
    return out


def test_hook_energy_separates_a_loud_open_from_a_flat_one():
    """
    A medida que a transcrição não dá: este clipe abre alto ou abre no vazio.

    Mesma fala nos dois casos; o que muda é só o nível dos 3 primeiros segundos.
    """
    words = [_word("a", 0.0, 10.0)]

    alto = summarize_loudness(
        _timeline([(0.0, 3.0, -14.0), (3.0, 10.0, -24.0)]), words, 10.0, hook_seconds=3.0
    )
    plano = summarize_loudness(
        _timeline([(0.0, 10.0, -24.0)]), words, 10.0, hook_seconds=3.0
    )

    assert alto.hook_energy == pytest.approx(10.0, abs=0.5)
    assert plano.hook_energy == pytest.approx(0.0, abs=0.5)


def test_peaks_are_not_reported_twice_for_the_same_moment():
    """Dois picos a meio segundo um do outro são um acontecimento só."""
    profile = summarize_loudness(
        _timeline([
            (0.0, 4.0, -30.0),
            (4.0, 4.4, -10.0),   # o grito
            (4.4, 4.6, -28.0),   # respiro no meio dele
            (4.6, 5.2, -11.0),   # o mesmo grito continuando
            (5.2, 20.0, -30.0),
        ]),
        [_word("a", 0.0, 20.0)],
        20.0,
    )

    # Um acontecimento no clipe inteiro: um pico relatado, no instante dele.
    assert len(profile.peaks) == 1
    assert profile.peaks[0][0] == pytest.approx(4.0, abs=1.0)


def test_pauses_are_only_the_stretches_well_below_speech():
    profile = summarize_loudness(
        _timeline([(0.0, 5.0, -24.0), (5.0, 7.5, -45.0), (7.5, 12.0, -24.0)]),
        [_word("a", 0.0, 12.0)],
        12.0,
    )

    assert len(profile.pauses) == 1
    inicio, fim = profile.pauses[0]
    assert inicio == pytest.approx(5.0, abs=0.2)
    assert fim == pytest.approx(7.5, abs=0.2)


def test_a_flat_clip_reports_no_peaks_at_all():
    """
    Sem nada acima da fala, o campo some — em vez de encher os três lugares.

    Relatar "picos" no nível da fala num clipe plano é a mesma armadilha que
    audio_events.py já documentou: a anotação aparece sempre e para de informar.
    """
    profile = summarize_loudness(
        _timeline([(0.0, 20.0, -24.0)]), [_word("a", 0.0, 20.0)], 20.0
    )
    assert profile.peaks == []
    assert "Picos de som" not in profile.as_prompt()


def test_a_clip_that_never_breathes_says_so_in_the_prompt():
    profile = summarize_loudness(
        _timeline([(0.0, 12.0, -24.0)]), [_word("a", 0.0, 12.0)], 12.0
    )
    assert not profile.pauses
    assert "não respira" in profile.as_prompt()


def test_no_audio_reading_degrades_instead_of_lying():
    """Sem curva não há perfil — e o prompt diz isso em vez de inventar números."""
    profile = summarize_loudness([], [_word("a", 0.0, 5.0)], 5.0)
    assert profile.speech_level is None
    assert profile.as_prompt() == "(sem leitura de áudio)"


def test_speech_level_falls_back_when_words_have_no_duration():
    """
    Música por cima da fala, ou palavra sem duração própria na transcrição.

    Sem a queda para a mediana do áudio audível, o bloco de som inteiro sumiria
    do prompt — justamente o que este módulo existe para evitar.
    """
    profile = summarize_loudness(
        _timeline([(0.0, 10.0, -20.0)]),
        [_word("a", 1.0, 1.0)],  # duração zero: não casa com amostra nenhuma
        10.0,
    )
    assert profile.speech_level == pytest.approx(-20.0, abs=0.5)


# ─── Cortes de edição ─────────────────────────────────────────────────────────

def test_cut_times_are_read_from_ffmpeg_metadata():
    saida = (
        "frame:0    pts:0       pts_time:0\n"
        "lavfi.scene_score=0.412\n"
        "frame:1    pts:87000   pts_time:3.628\n"
        "lavfi.scene_score=0.688\n"
    )
    assert parse_cut_times(saida) == [0.0, 3.63]


def test_garbage_lines_are_skipped_not_crashed():
    assert parse_cut_times("frame:1 pts_time:N/A\nlixo\n") == []


def test_cut_rhythm_reports_a_single_take_as_such():
    evidence = ClipEvidence(duration=30.0, cuts=[])
    assert "plano único" in evidence.cut_rhythm()

    picotado = ClipEvidence(duration=30.0, cuts=[2.0, 4.0, 6.0])
    assert "3 corte(s)" in picotado.cut_rhythm()


# ─── Leitura da imagem ────────────────────────────────────────────────────────

def _frames(times):
    return [Frame(time=t, jpeg=b"") for t in times]


def test_frame_notes_are_timed_by_the_frames_we_sent():
    """
    O instante vem do quadro enviado, nunca do que o modelo respondeu.

    É a falha mais cara possível aqui: uma observação ancorada no tempo errado
    chega à síntese com cara de fato e é cruzada com a curva de som, que está
    certa. O resultado é uma leitura confiante e falsa.
    """
    frames = _frames([0.0, 0.4, 12.5])
    data = {
        "frames": [
            {"on_screen": "rosto em close", "text_overlay": "ELE NÃO SABIA"},
            {"on_screen": "corte para a plateia", "text_overlay": None},
            {"on_screen": "volta para o close", "text_overlay": "OLHA A REAÇÃO"},
        ],
        "format": "rosto falando",
    }

    readout = build_readout(data, frames)

    assert [n.time for n in readout.frames] == [0.0, 0.4, 12.5]
    assert readout.frames[0].text_overlay == "ELE NÃO SABIA"
    assert readout.frames[1].text_overlay is None


def test_extra_frames_in_the_answer_are_dropped():
    """Um item a mais deslocaria todos os instantes seguintes."""
    readout = build_readout(
        {"frames": [{"on_screen": "a"}, {"on_screen": "b"}, {"on_screen": "c"}]},
        _frames([0.0, 1.0]),
    )
    assert [n.time for n in readout.frames] == [0.0, 1.0]


def test_empty_observations_are_skipped():
    readout = build_readout(
        {"frames": [{"on_screen": ""}, {"on_screen": "algo"}]}, _frames([0.0, 1.0])
    )
    assert len(readout.frames) == 1


def test_malformed_answer_yields_an_empty_readout_not_an_error():
    assert build_readout({}, _frames([0.0])).frames == []
    assert build_readout({"frames": ["texto solto"]}, _frames([0.0])).frames == []


def test_visual_prompt_carries_the_burned_in_text():
    """O texto queimado no vídeo não existe em nenhuma outra evidência."""
    readout = VisualReadout(
        frames=[FrameNote(time=0.0, on_screen="close", text_overlay="ELE NÃO SABIA")],
        video_format="rosto falando",
        caption_style="palavra a palavra, amarelo",
    )
    texto = readout.as_prompt()
    assert "ELE NÃO SABIA" in texto
    assert "rosto falando" in texto


# ─── Few-shot ─────────────────────────────────────────────────────────────────

def test_forensics_reach_the_prompt_as_cut_rules():
    linhas = PromptBuilder()._forensics_lines({
        "hook_breakdown": {"mechanism": "a tela promete o que o áudio ainda não deu"},
        "retention_devices": ["pergunta sem resposta", "contagem regressiva"],
        "transferable_rules": ["Comece na pergunta, nunca na resposta"],
        "production_notes": ["Use punch-in na ênfase"],
    })
    texto = "\n".join(linhas)

    assert "a tela promete" in texto
    assert "Comece na pergunta" in texto
    # Montagem fica de fora: quem lê este prompt escolhe intervalos, não monta.
    assert "punch-in" not in texto


def test_forensics_section_is_capped():
    """Um exemplo não pode sozinho dominar o bloco de few-shot."""
    linhas = PromptBuilder()._forensics_lines(
        {"transferable_rules": [f"regra {i}" for i in range(20)]}
    )
    assert len(linhas) == 3


def test_examples_without_forensics_are_unaffected():
    assert PromptBuilder()._forensics_lines({}) == []
    assert PromptBuilder()._forensics_lines(None) == []


# ─── API ──────────────────────────────────────────────────────────────────────

@pytest.fixture
def client(tmp_path, monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "storage_dir", str(tmp_path))
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'refs.db'}")
    factory = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)

    async def create():
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

    asyncio.run(create())

    async def override_get_db():
        async with factory() as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as test_client:
        yield test_client, factory
    app.dependency_overrides.clear()


def test_standalone_upload_needs_nothing_but_the_file(client, monkeypatch):
    """
    O caso de uso inteiro: um arquivo salvo do TikTok, sem saber de onde saiu.

    Nem URL, nem título, nem criador. Se qualquer um deles fosse obrigatório, o
    modo standalone não resolveria o problema que motivou sua existência.
    """
    test_client, _ = client
    monkeypatch.setattr(
        "app.routers.references.run_standalone_pipeline", lambda ref_id: None
    )

    response = test_client.post(
        "/api/references/standalone",
        files={"clip": ("viral.mp4", b"fake bytes", "video/mp4")},
    )

    assert response.status_code == 201
    body = response.json()
    assert body["kind"] == "standalone"
    assert body["status"] == "queued"
    assert body["source_url"] == ""
    assert body["source_title"] == "viral.mp4"


def test_standalone_upload_keeps_the_context_the_user_did_give(client, monkeypatch):
    test_client, _ = client
    monkeypatch.setattr(
        "app.routers.references.run_standalone_pipeline", lambda ref_id: None
    )

    response = test_client.post(
        "/api/references/standalone",
        files={"clip": ("viral.mp4", b"fake bytes", "video/mp4")},
        data={
            "title": "o clutch de 1v4",
            "channel": "@alguem",
            "post_url": "https://www.tiktok.com/@alguem/video/123",
            "source_type": "siege",
            "notas": "o texto na tela segura os 3 primeiros segundos",
        },
    )

    body = response.json()
    assert body["source_type"] == "siege"
    assert body["source_title"] == "o clutch de 1v4"
    assert body["notas"] == "o texto na tela segura os 3 primeiros segundos"


def test_unknown_niche_falls_back_instead_of_failing(client, monkeypatch):
    test_client, _ = client
    monkeypatch.setattr(
        "app.routers.references.run_standalone_pipeline", lambda ref_id: None
    )
    response = test_client.post(
        "/api/references/standalone",
        files={"clip": ("v.mp4", b"x", "video/mp4")},
        data={"source_type": "vlog-de-culinária"},
    )
    assert response.json()["source_type"] == "podcast"


def test_a_pdf_is_not_a_clip(client):
    test_client, _ = client
    response = test_client.post(
        "/api/references/standalone",
        files={"clip": ("relatorio.pdf", b"%PDF", "application/pdf")},
    )
    assert response.status_code == 422


def test_standalone_refuses_span_edits(client):
    """
    O clipe É o corte: não há original dentro do qual relocalizá-lo.

    Aceitar o ajuste corromperia o exemplo publicado, que grava start/end como
    os limites do clipe.
    """
    test_client, factory = client

    async def seed():
        async with factory() as db:
            db.add(ReferenceExample(
                id="r1", kind="standalone", source_url="", clip_path="c.mp4",
                status="done", source_start=0.0, source_end=32.0, clip_duration=32.0,
            ))
            await db.commit()

    asyncio.run(seed())

    recusado = test_client.patch("/api/references/r1", json={"source_start": 4.0})
    assert recusado.status_code == 409

    aceito = test_client.patch(
        "/api/references/r1", json={"performance": "viral", "views": 250000}
    )
    assert aceito.status_code == 200
    assert aceito.json()["views"] == 250000


# ─── Pipeline ─────────────────────────────────────────────────────────────────

@pytest.fixture
def db_factory(tmp_path, monkeypatch):
    """Banco isolado, com o AsyncSessionLocal do worker apontando para ele."""
    from app import database
    from app.workers import reference_pipeline

    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'pipe.db'}")
    factory = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)

    async def create():
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

    asyncio.run(create())
    monkeypatch.setattr(database, "AsyncSessionLocal", factory)
    monkeypatch.setattr(reference_pipeline, "AsyncSessionLocal", factory)
    return factory


def _stub_pipeline(monkeypatch, *, evidence=None, analysis=None, forensics=None):
    """Substitui tudo que sai da máquina: ffmpeg, AssemblyAI e Claude."""
    from types import SimpleNamespace

    from app.services.reference_analyzer import ReferenceAnalysis
    from app.services.transcriber import WordTimestamp
    from app.workers import reference_pipeline as rp

    async def fake_duration(path):
        return 32.5

    async def fake_audio(ref_id, clip_path):
        return f"{clip_path}.wav"

    async def fake_transcribe(job_id, audio_path):
        # WordTimestamp de verdade: o worker chama asdict() nas palavras, e um
        # dublê genérico esconderia essa dependência.
        return SimpleNamespace(
            words=[WordTimestamp(text="olha", start=0.0, end=0.4, confidence=0.9)],
            language="pt",
        )

    async def fake_evidence(**kwargs):
        return evidence or ClipEvidence(duration=32.5)

    async def fake_analysis(**kwargs):
        return (
            analysis
            or ReferenceAnalysis(
                hook="ELE NÃO SABIA",
                suggested_title="o dono estava na sala",
                virality_score=8.6,
                reason="o texto na tela promete antes de a fala entregar",
                tags=["revelação"],
                why_this_cut="abre no texto e fecha na reação",
            ),
            forensics if forensics is not None else {
                "hook_breakdown": {"mechanism": "a tela promete o que o áudio ainda não deu"},
                "transferable_rules": ["Comece na pergunta, nunca na resposta"],
            },
        )

    monkeypatch.setattr(rp, "get_duration", fake_duration)
    monkeypatch.setattr(rp, "_extract_clip_audio", fake_audio)
    monkeypatch.setattr(rp, "transcribe_audio", fake_transcribe)
    monkeypatch.setattr(rp, "gather_evidence", fake_evidence)
    monkeypatch.setattr(rp, "analyze_standalone_clip", fake_analysis)


def test_standalone_pipeline_fills_the_columns_confirm_will_read(db_factory, monkeypatch):
    """
    A fiação do worker até o banco.

    É aqui que erro de nome de coluna ou de string de status se esconde: nada
    estoura, o pipeline termina, e só na hora de publicar o exemplo se descobre
    que o campo está vazio.
    """
    from app.workers.reference_pipeline import run_standalone_pipeline

    _stub_pipeline(monkeypatch)

    async def run():
        async with db_factory() as db:
            db.add(ReferenceExample(
                id="s1", kind="standalone", source_url="", clip_path="clipe.mp4",
                source_type="siege", status="queued",
            ))
            await db.commit()

        await run_standalone_pipeline("s1")

        async with db_factory() as db:
            return await db.get(ReferenceExample, "s1")

    ref = asyncio.run(run())

    assert ref.status == "done"
    assert ref.error_message is None
    assert ref.language == "pt"
    assert ref.clip_duration == 32.5
    # O corte é o clipe inteiro — é isso que faz o confirm() funcionar sem
    # precisar saber de qual dos dois pipelines a referência veio.
    assert ref.source_start == 0.0
    assert ref.source_end == 32.5
    assert '"hook": "ELE N' in ref.analysis_json
    assert "transferable_rules" in ref.forensics_json


def test_standalone_pipeline_records_the_failure_instead_of_dying_quietly(
    db_factory, monkeypatch
):
    from app.workers import reference_pipeline as rp

    _stub_pipeline(monkeypatch)

    async def explode(path):
        raise RuntimeError("arquivo sem duração declarada")

    monkeypatch.setattr(rp, "get_duration", explode)

    async def run():
        async with db_factory() as db:
            db.add(ReferenceExample(
                id="s2", kind="standalone", source_url="", clip_path="quebrado.mp4",
                status="queued",
            ))
            await db.commit()
        await rp.run_standalone_pipeline("s2")
        async with db_factory() as db:
            return await db.get(ReferenceExample, "s2")

    ref = asyncio.run(run())
    assert ref.status == "error"
    assert "sem duração" in ref.error_message


def test_published_example_carries_the_forensics_and_no_fake_cut_position(
    client, monkeypatch
):
    """
    O exemplo publicado alimenta o PromptBuilder e o pattern_miner.

    `video.duration` fica em 0 de propósito: é a duração do vídeo ORIGINAL, e
    aqui não há original. Se puséssemos a duração do clipe, o miner calcularia
    start/duration = 0 e todo exemplo standalone entraria como "corte no início
    do vídeo" — uma estatística inventada sobre um vídeo que ninguém viu.
    """
    import json as _json

    test_client, factory = client

    async def seed():
        async with factory() as db:
            db.add(ReferenceExample(
                id="s3", kind="standalone", source_url="", clip_path="c.mp4",
                source_type="gameplay", status="done",
                source_start=0.0, source_end=32.5, clip_duration=32.5,
                performance="viral", views=1200000, language="pt",
                analysis_json=_json.dumps({
                    "hook": "ELE NÃO SABIA", "suggested_title": "t",
                    "virality_score": 8.6, "reason": "r", "tags": ["revelação"],
                    "why_this_cut": "w",
                }),
                forensics_json=_json.dumps({
                    "transferable_rules": ["Comece na pergunta, nunca na resposta"],
                }),
            ))
            await db.commit()

    asyncio.run(seed())

    response = test_client.post("/api/references/s3/confirm")
    assert response.status_code == 201

    caminho = Path(response.json()["example_path"])
    try:
        example = _json.loads(caminho.read_text(encoding="utf-8"))
        assert example["source"] == "external_clip"
        assert example["source_type"] == "gameplay"
        assert example["video"]["duration"] == 0
        assert example["clip"]["duration"] == 32.5
        assert example["forensics"]["transferable_rules"]

        # E o PromptBuilder aproveita: a regra de corte chega ao prompt.
        assert any(
            "Comece na pergunta" in linha
            for linha in PromptBuilder()._forensics_lines(example["forensics"])
        )
    finally:
        caminho.unlink(missing_ok=True)


# ─── Compatibilidade com o SDK instalado ──────────────────────────────────────

def _sdk_spy(monkeypatch, module, resposta: str) -> dict:
    """
    Um cliente falso cuja `create()` tem a assinatura REAL do SDK instalado.

    O dublê comum aceita qualquer coisa e por isso não viu o erro que derrubou
    a primeira referência de verdade: o código passava `thinking=`, que o
    anthropic==0.40.0 do projeto não conhece. Com `sig.bind`, um argumento que
    o SDK não aceita levanta TypeError aqui, em 1s e de graça, em vez de depois
    da transcrição e da chamada de visão já terem sido pagas.
    """
    import inspect
    from types import SimpleNamespace

    import anthropic

    assinatura = inspect.signature(anthropic.AsyncAnthropic(api_key="x").messages.create)
    capturado: dict = {}

    class FakeMessages:
        async def create(self, **kwargs):
            assinatura.bind(**kwargs)  # levanta se algum argumento não existir no SDK
            capturado.update(kwargs)
            return SimpleNamespace(
                content=[SimpleNamespace(type="text", text=resposta)],
                stop_reason="end_turn",
            )

    class FakeClient:
        def __init__(self, *args, **kwargs):
            self.messages = FakeMessages()

    monkeypatch.setattr(module, "anthropic", SimpleNamespace(
        AsyncAnthropic=FakeClient,
        APIError=anthropic.APIError,
    ))
    return capturado


def test_synthesis_call_only_uses_arguments_the_installed_sdk_accepts(monkeypatch):
    import json as _json

    from app.services import reference_analyzer

    resposta = _json.dumps({
        "hook": "ELE NÃO SABIA",
        "suggested_title": "t",
        "virality_score": 8.6,
        "reason": "r",
        "tags": ["revelação"],
        "why_this_cut": "w",
        "forensics": {"transferable_rules": ["Comece na pergunta"]},
    })
    capturado = _sdk_spy(monkeypatch, reference_analyzer, resposta)

    analysis, forensics = asyncio.run(reference_analyzer.analyze_standalone_clip(
        reference_id="r1",
        evidence=ClipEvidence(duration=32.5, words=[_word("olha", 0.0, 0.4)]),
        title="t", channel="c", source_type="gameplay", language="pt", notas="",
    ))

    assert analysis.virality_score == 8.6
    assert forensics["transferable_rules"] == ["Comece na pergunta"]
    assert capturado["model"]
    assert capturado["max_tokens"] > 0


def test_vision_call_only_uses_arguments_the_installed_sdk_accepts(monkeypatch):
    import json as _json

    from app.services import clip_forensics as cf

    resposta = _json.dumps({
        "frames": [{"on_screen": "close", "text_overlay": "ELE NÃO SABIA"}],
        "format": "rosto falando",
    })
    capturado = _sdk_spy(monkeypatch, cf, resposta)

    readout = asyncio.run(cf.read_frames("r1", [Frame(time=0.0, jpeg=b"x")]))

    assert readout.frames[0].text_overlay == "ELE NÃO SABIA"
    assert capturado["model"]


def test_truncated_synthesis_says_it_was_truncated(monkeypatch):
    """
    Bater no teto de tokens tem que se anunciar como isso.

    O JSON pela metade que volta faz o parser reclamar de uma aspa não fechada
    na linha 27 — pista que não leva a lugar nenhum. Aconteceu no primeiro
    clipe real, e custou uma rodada inteira de diagnóstico.
    """
    from types import SimpleNamespace

    import anthropic

    from app.services import reference_analyzer

    class FakeMessages:
        async def create(self, **kwargs):
            return SimpleNamespace(
                content=[SimpleNamespace(type="text", text='{"hook": "ELE NÃO SAB')],
                stop_reason="max_tokens",
            )

    class FakeClient:
        def __init__(self, *args, **kwargs):
            self.messages = FakeMessages()

    monkeypatch.setattr(reference_analyzer, "anthropic", SimpleNamespace(
        AsyncAnthropic=FakeClient, APIError=anthropic.APIError,
    ))

    with pytest.raises(RuntimeError, match="truncada"):
        asyncio.run(reference_analyzer.analyze_standalone_clip(
            reference_id="r1",
            evidence=ClipEvidence(duration=32.5),
            title="", channel="", source_type="gameplay", language="pt", notas="",
        ))
