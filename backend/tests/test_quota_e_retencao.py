"""
As travas de custo e a faxina do disco.

Estas existem por um motivo só: transcrição e análise são cobradas por minuto de
áudio, e o prejuízo de um teto ausente aparece dias depois, no cartão, não no
log. Por isso os testes insistem num ponto: toda guarda tem que barrar ANTES do
download, porque recusar depois já custou exatamente o que se queria evitar.
"""

import asyncio
from datetime import datetime, timedelta, timezone

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config import settings
from app.database import Base, get_db
from app.main import register_routers
from app.models import Clip, Job, Transcript
from app.services import quota, retention


@pytest.fixture
def ambiente(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "public_build", False)
    monkeypatch.setattr(settings, "clipmint_password", "")
    monkeypatch.setattr(settings, "storage_dir", str(tmp_path / "storage"))
    settings.ensure_dirs()

    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'q.db'}")
    factory = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)

    async def criar():
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

    asyncio.run(criar())

    async def override_db():
        async with factory() as session:
            yield session

    app = FastAPI()
    register_routers(app)
    app.dependency_overrides[get_db] = override_db
    return TestClient(app), factory


def _duracao_falsa(
    monkeypatch, segundos: float, ao_vivo: bool = False, consulta_ok: bool = True
) -> None:
    async def falso(url: str) -> quota.Metadados:
        return quota.Metadados(duration=segundos, is_live=ao_vivo, ok=consulta_ok)

    monkeypatch.setattr(quota, "probe", falso)


def _criar(cliente, url="https://youtu.be/dQw4w9WgXcQ"):
    return cliente.post(
        "/api/jobs", json={"youtube_url": url, "source_type": "podcast"}
    )


# ─── Teto de duração ───────────────────────────────────────────────────────────

def test_video_longo_demais_e_recusado_antes_de_baixar(ambiente, monkeypatch):
    cliente, _ = ambiente
    monkeypatch.setattr(settings, "max_source_minutes", 120)
    _duracao_falsa(monkeypatch, 3 * 3600)  # 3 horas

    resp = _criar(cliente)
    assert resp.status_code == 422
    assert "180 minutos" in resp.text and "120" in resp.text


def test_video_dentro_do_teto_passa(ambiente, monkeypatch):
    cliente, _ = ambiente
    monkeypatch.setattr(settings, "max_source_minutes", 120)
    _duracao_falsa(monkeypatch, 60 * 60)
    assert _criar(cliente).status_code == 201


def test_duracao_medida_e_guardada_no_job(ambiente, monkeypatch):
    """
    Sem isso, dez pedidos disparados juntos passariam todos.

    A cota soma a duração dos jobs da janela; se o job nascesse sem duração e só
    a ganhasse depois do download, os pedidos simultâneos não veriam uns aos
    outros.
    """
    cliente, _ = ambiente
    _duracao_falsa(monkeypatch, 900.0)
    resp = _criar(cliente)
    assert resp.json()["duration_seconds"] == 900.0


def test_versao_pessoal_nao_tem_teto_de_duracao_por_padrao(ambiente, monkeypatch):
    """Quem manda o link é quem paga por ele."""
    cliente, _ = ambiente
    monkeypatch.setattr(settings, "max_source_minutes", 0)
    monkeypatch.setattr(settings, "public_build", False)
    _duracao_falsa(monkeypatch, 8 * 3600)
    assert _criar(cliente).status_code == 201


def test_build_publico_tem_teto_proprio(monkeypatch):
    """Lá quem paga a conta não é quem escolhe o vídeo."""
    monkeypatch.setattr(settings, "max_source_minutes", 0)
    monkeypatch.setattr(settings, "public_max_source_minutes", 120)

    monkeypatch.setattr(settings, "public_build", False)
    assert quota.max_source_seconds() == 0

    monkeypatch.setattr(settings, "public_build", True)
    assert quota.max_source_seconds() == 120 * 60


def test_sem_teto_a_duracao_desconhecida_passa(monkeypatch):
    """Sem limite para conferir, não há por que recusar."""
    monkeypatch.setattr(settings, "max_source_minutes", 0)
    monkeypatch.setattr(settings, "public_build", False)
    quota.check_duration(quota.Metadados(ok=False))  # não levanta


def test_com_teto_a_duracao_desconhecida_e_RECUSADA(monkeypatch):
    """
    A lição mais cara desta fatia.

    A primeira versão deixava passar quando a consulta de metadados falhava —
    "um soluço de rede não deve recusar trabalho legítimo". Mas consulta e
    download falham por motivos DIFERENTES: num teste real, o link de uma live
    devolveu "This live stream recording is not available" na consulta e baixou
    normalmente em seguida — 18 GB antes de alguém perceber.

    O caminho de escape do guarda era justamente o que o vídeo caro percorria.
    """
    monkeypatch.setattr(settings, "max_source_minutes", 10)

    # Consulta falhou
    with pytest.raises(HTTPException) as exc:
        quota.check_duration(quota.Metadados(ok=False))
    assert exc.value.status_code == 422
    assert "duração" in exc.value.detail

    # Consulta respondeu, mas sem duração
    with pytest.raises(HTTPException):
        quota.check_duration(quota.Metadados(duration=0.0, ok=True))


def test_job_nao_e_criado_quando_a_consulta_falha_com_teto(ambiente, monkeypatch):
    """O caso de ponta a ponta: nada entra no banco, nada é baixado."""
    cliente, _ = ambiente
    monkeypatch.setattr(settings, "max_source_minutes", 10)
    _duracao_falsa(monkeypatch, 0.0, consulta_ok=False)

    resp = _criar(cliente, "https://youtu.be/metadadoQuebrado")
    assert resp.status_code == 422
    assert cliente.get("/api/jobs").json() == []


# ─── Cota por janela ───────────────────────────────────────────────────────────

def _semear_jobs(factory, quantos: int, minutos_cada: float, idade_horas: float = 0):
    async def executar():
        async with factory() as db:
            from sqlalchemy import select

            from app.models import User

            dono = (await db.execute(select(User))).scalars().first()
            quando = datetime.now(timezone.utc) - timedelta(hours=idade_horas)
            for i in range(quantos):
                db.add(
                    Job(
                        id=f"antigo-{idade_horas}-{i}",
                        user_id=dono.id if dono else None,
                        youtube_url=f"https://youtu.be/x{i}",
                        duration_seconds=minutos_cada * 60,
                        status="done",
                        created_at=quando,
                    )
                )
            await db.commit()

    asyncio.run(executar())


def test_versao_pessoal_nao_tem_cota_por_padrao(ambiente, monkeypatch):
    """
    Lá é uma pessoa, na própria conta de API, processando o que quer.

    Uma cota na ferramenta pessoal atrapalharia o trabalho — processar uma live
    de 6 horas é uso normal ali — sem proteger ninguém.
    """
    cliente, _ = ambiente
    monkeypatch.setattr(settings, "public_build", False)
    _duracao_falsa(monkeypatch, 6 * 3600)
    for i in range(4):
        assert _criar(cliente, f"https://youtu.be/longo{i}").status_code == 201


def test_cota_de_janela_sai_de_cena_quando_ha_cobranca(monkeypatch):
    """Com saldo, quem trava o custo é o saldo.

    A cota por janela era a trava enquanto o uso era grátis. Mantê-la junto da
    cobrança significaria recusar trabalho de quem PAGOU por ele — pior que não
    ter limite nenhum. O teto EXPLÍCITO sobrevive, como alavanca de emergência.
    """
    monkeypatch.setattr(settings, "quota_max_videos", 0)
    monkeypatch.setattr(settings, "quota_max_minutes", 0)
    monkeypatch.setattr(settings, "public_quota_max_videos", 10)
    monkeypatch.setattr(settings, "public_quota_max_minutes", 300)

    # Versão pessoal: sem cobrança e sem cota — é a conta de API do próprio dono.
    monkeypatch.setattr(settings, "public_build", False)
    assert quota.quota_limits() == (0, 0)

    # Build público = build com cobrança: os padrões públicos não se aplicam.
    monkeypatch.setattr(settings, "public_build", True)
    assert quota.quota_limits() == (0, 0)

    # Mas o que o operador escreveu à mão continua valendo.
    monkeypatch.setattr(settings, "quota_max_videos", 3)
    monkeypatch.setattr(settings, "quota_max_minutes", 90)
    assert quota.quota_limits() == (3, 90)


def test_teto_de_videos_por_janela(ambiente, monkeypatch):
    cliente, factory = ambiente
    monkeypatch.setattr(settings, "quota_max_videos", 3)
    monkeypatch.setattr(settings, "quota_max_minutes", 0)
    _duracao_falsa(monkeypatch, 60.0)

    for i in range(3):
        assert _criar(cliente, f"https://youtu.be/a{i}").status_code == 201

    resp = _criar(cliente, "https://youtu.be/estouro")
    assert resp.status_code == 429
    assert "3 vídeos" in resp.text


def test_teto_de_minutos_por_janela(ambiente, monkeypatch):
    """
    O teto que realmente segura a conta.

    Dez vídeos de duas horas custam vinte vezes mais que dez de seis minutos —
    contar só a quantidade não protegeria nada.
    """
    cliente, factory = ambiente
    monkeypatch.setattr(settings, "quota_max_videos", 0)
    monkeypatch.setattr(settings, "quota_max_minutes", 100)

    _duracao_falsa(monkeypatch, 90 * 60)  # 90 min
    assert _criar(cliente, "https://youtu.be/primeiro").status_code == 201

    _duracao_falsa(monkeypatch, 30 * 60)  # levaria a 120 > 100
    resp = _criar(cliente, "https://youtu.be/segundo")
    assert resp.status_code == 429
    assert "minutos" in resp.text


def test_a_mensagem_de_cota_diz_quanto_ainda_cabe(ambiente, monkeypatch):
    cliente, _ = ambiente
    monkeypatch.setattr(settings, "quota_max_videos", 0)
    monkeypatch.setattr(settings, "quota_max_minutes", 100)

    _duracao_falsa(monkeypatch, 60 * 60)
    _criar(cliente, "https://youtu.be/um")

    _duracao_falsa(monkeypatch, 90 * 60)
    resp = _criar(cliente, "https://youtu.be/dois")
    assert resp.status_code == 429
    assert "40 minutos" in resp.text  # o que sobrou
    assert "90" in resp.text          # o tamanho do pedido


def test_janela_e_deslizante_e_libera_o_que_envelheceu(ambiente, monkeypatch):
    """
    Com "por dia", quem estoura às 23h volta a ter tudo às 00h.

    Aqui o que sai da janela deixa de contar, e o pico de abuso não cabe em duas
    horas.
    """
    cliente, factory = ambiente
    monkeypatch.setattr(settings, "quota_window_hours", 24)
    monkeypatch.setattr(settings, "quota_max_videos", 2)
    monkeypatch.setattr(settings, "quota_max_minutes", 0)
    _duracao_falsa(monkeypatch, 60.0)

    # Cria o dono e dois jobs de 30h atrás — fora da janela.
    assert _criar(cliente, "https://youtu.be/agora").status_code == 201
    _semear_jobs(factory, quantos=5, minutos_cada=10, idade_horas=30)

    # Os 5 antigos não contam; ainda cabe mais um dentro do teto de 2.
    assert _criar(cliente, "https://youtu.be/mais-um").status_code == 201
    # E o terceiro dentro da janela estoura.
    assert _criar(cliente, "https://youtu.be/terceiro").status_code == 429


def test_cota_desligada_nao_barra_nada(ambiente, monkeypatch):
    cliente, _ = ambiente
    monkeypatch.setattr(settings, "quota_max_videos", 0)
    monkeypatch.setattr(settings, "quota_max_minutes", 0)
    _duracao_falsa(monkeypatch, 60.0)
    for i in range(6):
        assert _criar(cliente, f"https://youtu.be/z{i}").status_code == 201


# ─── Duplicata ─────────────────────────────────────────────────────────────────

def test_mesmo_link_em_andamento_e_recusado(ambiente, monkeypatch):
    """Dois cliques custavam dois downloads e duas transcrições do mesmo vídeo."""
    cliente, factory = ambiente
    _duracao_falsa(monkeypatch, 60.0)

    primeiro = _criar(cliente, "https://youtu.be/mesmo")
    assert primeiro.status_code == 201

    async def marcar_em_andamento():
        async with factory() as db:
            await db.execute(
                Job.__table__.update()
                .where(Job.id == primeiro.json()["id"])
                .values(status="downloading")
            )
            await db.commit()

    asyncio.run(marcar_em_andamento())

    resp = _criar(cliente, "https://youtu.be/mesmo")
    assert resp.status_code == 409
    assert "já está sendo processado" in resp.text


def test_reprocessar_video_ja_concluido_e_permitido(ambiente, monkeypatch):
    """Mudou o preset, mudou o modo de legenda — é pedido legítimo."""
    cliente, factory = ambiente
    _duracao_falsa(monkeypatch, 60.0)

    primeiro = _criar(cliente, "https://youtu.be/mesmo")
    async def concluir():
        async with factory() as db:
            await db.execute(
                Job.__table__.update()
                .where(Job.id == primeiro.json()["id"])
                .values(status="done")
            )
            await db.commit()

    asyncio.run(concluir())
    assert _criar(cliente, "https://youtu.be/mesmo").status_code == 201


# ─── Retenção ──────────────────────────────────────────────────────────────────

def _semear_clip(factory, tmp_path, clip_id: str, idade_dias: float):
    arquivo = tmp_path / f"{clip_id}.mp4"
    arquivo.write_bytes(b"x" * 1000)

    async def executar():
        async with factory() as db:
            db.add(Job(id=f"job-{clip_id}", youtube_url="u", status="done"))
            db.add(
                Clip(
                    id=clip_id,
                    job_id=f"job-{clip_id}",
                    start_time=0,
                    end_time=30,
                    duration=30,
                    virality_score=8.5,
                    hook="um gancho",
                    views=12345,
                    status="ready",
                    file_path=str(arquivo),
                    file_size_bytes=1000,
                    created_at=datetime.now(timezone.utc) - timedelta(days=idade_dias),
                )
            )
            await db.commit()

    asyncio.run(executar())
    return arquivo


def test_clipe_vencido_perde_o_arquivo_mas_nao_a_linha(ambiente, tmp_path, monkeypatch):
    """
    A nota e o desempenho real alimentam o few-shot.

    Apagar a linha para economizar bytes destruiria o aprendizado do sistema —
    e os bytes não são dela, são do arquivo.
    """
    _, factory = ambiente
    monkeypatch.setattr(settings, "clip_ttl_days", 14)
    arquivo = _semear_clip(factory, tmp_path, "velho", idade_dias=30)

    async def executar():
        async with factory() as db:
            return await retention.faxina(db)

    r = asyncio.run(executar())

    assert r.clipes_expirados == 1
    assert not arquivo.exists(), "o arquivo continuou no disco"

    async def ler():
        from sqlalchemy import select

        async with factory() as db:
            return (await db.execute(select(Clip).where(Clip.id == "velho"))).scalar_one()

    clip = asyncio.run(ler())
    assert clip.status == retention.EXPIRED
    assert clip.file_path is None
    # O que o sistema aprende com este clipe continua lá.
    assert clip.virality_score == 8.5
    assert clip.hook == "um gancho"
    assert clip.views == 12345


def test_clipe_novo_nao_e_tocado(ambiente, tmp_path, monkeypatch):
    _, factory = ambiente
    monkeypatch.setattr(settings, "clip_ttl_days", 14)
    arquivo = _semear_clip(factory, tmp_path, "novo", idade_dias=2)

    async def executar():
        async with factory() as db:
            return await retention.faxina(db)

    r = asyncio.run(executar())
    assert r.clipes_expirados == 0
    assert arquivo.exists()


def test_ttl_desligado_nao_apaga_nada(ambiente, tmp_path, monkeypatch):
    _, factory = ambiente
    monkeypatch.setattr(settings, "clip_ttl_days", 0)
    arquivo = _semear_clip(factory, tmp_path, "eterno", idade_dias=365)

    async def executar():
        async with factory() as db:
            return await retention.faxina(db)

    asyncio.run(executar())
    assert arquivo.exists()


def test_video_de_origem_de_job_em_andamento_nao_e_apagado(ambiente, monkeypatch):
    """Arrancaria o arquivo debaixo do FFmpeg."""
    _, factory = ambiente
    monkeypatch.setattr(settings, "download_ttl_days", 1)

    pasta = settings.downloads_dir / "rodando"
    pasta.mkdir(parents=True, exist_ok=True)
    (pasta / "video.mp4").write_bytes(b"y" * 500)

    async def preparar():
        async with factory() as db:
            db.add(
                Job(
                    id="rodando",
                    youtube_url="u",
                    status="clipping",
                    updated_at=datetime.now(timezone.utc) - timedelta(days=10),
                )
            )
            await db.commit()
            return await retention.faxina(db)

    r = asyncio.run(preparar())
    assert r.downloads_apagados == 0
    assert (pasta / "video.mp4").exists()


def test_pasta_nomeada_por_pessoa_e_preservada(ambiente):
    """
    Backup manual não pode ser apagado por faxina automática.

    No storage de desenvolvimento havia `86aebb59_pre-correcao-1603` e
    `..._pre-reanalise-20260817` — alguém guardou aquilo de propósito antes de
    mexer em algo, e a primeira versão desta limpeza os teria levado.
    """
    _, factory = ambiente
    manual = settings.clips_dir / "abc123_pre-correcao-1603"
    manual.mkdir(parents=True, exist_ok=True)
    (manual / "clip.mp4").write_bytes(b"z" * 100)

    orfa = settings.clips_dir / ("f" * 32)  # nome de job de verdade
    orfa.mkdir(parents=True, exist_ok=True)
    (orfa / "clip.mp4").write_bytes(b"z" * 100)

    async def executar():
        async with factory() as db:
            return await retention.faxina(db)

    r = asyncio.run(executar())

    assert manual.exists(), "backup manual foi apagado"
    assert not orfa.exists(), "pasta órfã de verdade não foi limpa"
    assert r.pastas_orfas == 1


def test_transcricao_orfa_e_removida_com_o_json(ambiente):
    """
    No Postgres elas chegam a IMPEDIR a migração (chave estrangeira).

    Ver docs/DECISOES.md, D34.
    """
    _, factory = ambiente
    json_path = settings.transcripts_dir / "orfa_words.json"
    json_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text("[]", encoding="utf-8")

    async def executar():
        async with factory() as db:
            db.add(
                Transcript(
                    id="t1",
                    job_id="job-que-nao-existe",
                    full_text="oi",
                    words_json_path=str(json_path),
                )
            )
            await db.commit()
            return await retention.faxina(db)

    r = asyncio.run(executar())
    assert r.transcricoes_orfas == 1
    assert not json_path.exists()


def test_dry_run_nao_apaga_nada(ambiente, tmp_path, monkeypatch):
    _, factory = ambiente
    monkeypatch.setattr(settings, "clip_ttl_days", 1)
    arquivo = _semear_clip(factory, tmp_path, "velhote", idade_dias=99)

    async def executar():
        async with factory() as db:
            return await retention.faxina(db, dry_run=True)

    r = asyncio.run(executar())
    assert r.clipes_expirados == 1, "o dry-run tem que CONTAR o que sairia"
    assert arquivo.exists(), "o dry-run apagou"


# ─── Transmissão ao vivo ───────────────────────────────────────────────────────

def test_live_em_andamento_e_recusada(ambiente, monkeypatch):
    """
    Live não tem duração, então escapava do teto.

    Pior: o yt-dlp apontado para uma começa a GRAVÁ-LA, sem fim previsto —
    disco, banda e minutos de transcrição crescendo enquanto a transmissão
    durar. Foi assim que o caso apareceu, testando o teto com um link real.
    """
    cliente, _ = ambiente
    _duracao_falsa(monkeypatch, 0.0, ao_vivo=True)

    resp = _criar(cliente, "https://youtu.be/aoVivoAgora")
    assert resp.status_code == 422
    assert "ao vivo" in resp.text


def test_gravacao_de_live_encerrada_passa(ambiente, monkeypatch):
    """Já acabou, tem duração, é material legítimo."""
    cliente, _ = ambiente
    _duracao_falsa(monkeypatch, 45 * 60, ao_vivo=False)
    assert _criar(cliente, "https://youtu.be/liveGravada").status_code == 201


def test_live_e_recusada_nas_duas_versoes(monkeypatch):
    """Não é questão de quem paga: o produto não sabe fazer isso."""
    for publico in (True, False):
        monkeypatch.setattr(settings, "public_build", publico)
        with pytest.raises(HTTPException) as exc:
            quota.check_live(quota.Metadados(is_live=True))
        assert exc.value.status_code == 422
