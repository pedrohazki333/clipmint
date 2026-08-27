"""
O que sai do disco, quando, e o que nunca sai.

Vídeo ocupa muito espaço, e um servidor que só acumula enche — e um disco cheio
não degrada, ele PARA: o FFmpeg falha, o banco recusa escrita, e tudo cai de
uma vez. Por isso a faxina é automática, não um lembrete.

O que é apagado, e por quê a distinção importa:

  - **vídeo de origem** (`downloads/<job>/`): sai primeiro, e cedo. É o que
    ocupa GB de verdade e só serve para re-renderizar. Depois de apagado,
    "Retomar" continua funcionando — só volta a baixar.
  - **arquivo do clipe** (`clips/<job>/*.mp4`): sai depois do prazo de
    retenção. É o entregável; presume-se que quem gerou já baixou.

O que **nunca** é apagado por aqui: as LINHAS do banco. Nota de viralidade,
eixos da rubrica, o que foi aprendido e o desempenho real depois de postado são
o que alimenta o few-shot — apagá-los destruiria o aprendizado do sistema para
economizar bytes que não são deles. O clipe expirado vira `status='expired'`,
que a interface sabe explicar.
"""

import logging
import re
import shutil
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models import Clip, Job, Transcript

logger = logging.getLogger(__name__)

#: Status de um clipe cujo arquivo já saiu do disco. A linha continua no banco.
EXPIRED = "expired"

#: Um id de job: 32 caracteres hexadecimais (uuid4 sem hifens).
#:
#: A faxina só toca em pasta cujo nome bate com isto. Uma pasta com nome fora do
#: padrão foi nomeada por uma PESSOA — no storage de desenvolvimento havia
#: `86aebb59_pre-correcao-1603` e `..._pre-reanalise-20260817`, backups manuais
#: feitos à mão antes de mexer em algo. Uma limpeza automática que os apagasse
#: destruiria justamente o que alguém guardou de propósito.
_ID_DE_JOB = re.compile(r"^[0-9a-f]{32}$")


@dataclass
class FaxinaResultado:
    clipes_expirados: int = 0
    bytes_de_clipes: int = 0
    downloads_apagados: int = 0
    bytes_de_downloads: int = 0
    transcricoes_orfas: int = 0
    pastas_orfas: int = 0
    bytes_orfaos: int = 0
    detalhes: list[str] = field(default_factory=list)

    @property
    def bytes_totais(self) -> int:
        return self.bytes_de_clipes + self.bytes_de_downloads + self.bytes_orfaos

    def resumo(self) -> str:
        return (
            f"{self.clipes_expirados} clipe(s) expirado(s), "
            f"{self.downloads_apagados} download(s) apagado(s), "
            f"{self.transcricoes_orfas} transcrição(ões) órfã(s), "
            f"{self.pastas_orfas} pasta(s) órfã(s) — "
            f"{self.bytes_totais / 1e9:.2f} GB liberados"
        )


def _tamanho(caminho: Path) -> int:
    if not caminho.exists():
        return 0
    if caminho.is_file():
        return caminho.stat().st_size
    return sum(f.stat().st_size for f in caminho.rglob("*") if f.is_file())


def _agora() -> datetime:
    return datetime.now(timezone.utc)


def _com_fuso(valor: datetime | None) -> datetime | None:
    """O SQLite devolve datetime sem fuso; comparar com um aware estoura."""
    if valor is None:
        return None
    return valor if valor.tzinfo else valor.replace(tzinfo=timezone.utc)


async def expirar_clipes(db: AsyncSession, dry_run: bool = False) -> tuple[int, int]:
    """Apaga o ARQUIVO dos clipes vencidos. A linha no banco fica."""
    dias = settings.clip_ttl_days
    if not dias:
        return 0, 0

    limite = _agora() - timedelta(days=dias)
    clipes = (
        await db.execute(
            select(Clip).where(Clip.status == "ready", Clip.file_path.is_not(None))
        )
    ).scalars().all()

    quantos, bytes_liberados = 0, 0
    ids: list[str] = []
    for clip in clipes:
        criado = _com_fuso(clip.created_at)
        if criado is None or criado > limite:
            continue
        caminho = Path(clip.file_path)
        bytes_liberados += _tamanho(caminho)
        quantos += 1
        ids.append(clip.id)
        if not dry_run:
            caminho.unlink(missing_ok=True)

    if ids and not dry_run:
        await db.execute(
            update(Clip)
            .where(Clip.id.in_(ids))
            .values(status=EXPIRED, file_path=None, file_size_bytes=None)
        )
        await db.commit()

    return quantos, bytes_liberados


async def apagar_downloads(db: AsyncSession, dry_run: bool = False) -> tuple[int, int]:
    """
    Apaga o vídeo de origem de jobs já terminados.

    Só de job terminado: apagar a fonte de um job em andamento arrancaria o
    arquivo debaixo do FFmpeg.
    """
    dias = settings.download_ttl_days
    if not dias:
        return 0, 0

    limite = _agora() - timedelta(days=dias)
    jobs = (
        await db.execute(
            select(Job).where(Job.status.in_(("done", "error")))
        )
    ).scalars().all()

    quantos, bytes_liberados = 0, 0
    ids: list[str] = []
    for job in jobs:
        atualizado = _com_fuso(job.updated_at) or _com_fuso(job.created_at)
        if atualizado is None or atualizado > limite:
            continue
        pasta = settings.downloads_dir / job.id
        tamanho = _tamanho(pasta)
        if not tamanho:
            continue
        bytes_liberados += tamanho
        quantos += 1
        ids.append(job.id)
        if not dry_run:
            shutil.rmtree(pasta, ignore_errors=True)

    if ids and not dry_run:
        # As colunas apontariam para arquivos que não existem mais. O resume
        # trata caminho ausente re-baixando, mas deixar o caminho no banco faria
        # o log dizer "mídia não confiável" em vez de "não está aqui".
        await db.execute(
            update(Job).where(Job.id.in_(ids)).values(video_path=None, audio_path=None)
        )
        await db.commit()

    return quantos, bytes_liberados


async def limpar_orfaos(db: AsyncSession, dry_run: bool = False) -> tuple[int, int, int]:
    """
    Remove o que sobrou de jobs que já não existem.

    São as linhas e pastas que o `DELETE` de um job em execução deixava para
    trás antes da correção da Fatia 3 — nenhuma nova aparece, mas as antigas
    seguem ocupando espaço, e no Postgres elas chegam a IMPEDIR a migração
    (chave estrangeira; ver docs/DECISOES.md, D34).
    """
    ids_de_jobs = set(
        (await db.execute(select(Job.id))).scalars().all()
    )

    # Transcrições apontando para job inexistente
    orfas = [
        t
        for t in (await db.execute(select(Transcript))).scalars().all()
        if t.job_id not in ids_de_jobs
    ]
    if orfas and not dry_run:
        for t in orfas:
            if t.words_json_path:
                Path(t.words_json_path).unlink(missing_ok=True)
        await db.execute(
            Transcript.__table__.delete().where(
                Transcript.id.in_([t.id for t in orfas])
            )
        )
        await db.commit()

    # Pastas de storage sem job correspondente
    pastas, bytes_liberados = 0, 0
    for base in (settings.downloads_dir, settings.clips_dir):
        if not base.exists():
            continue
        for pasta in base.iterdir():
            if not pasta.is_dir() or pasta.name in ids_de_jobs:
                continue
            if not _ID_DE_JOB.match(pasta.name):
                # Nome fora do padrão = alguém batizou essa pasta à mão. Fica.
                logger.info(
                    f"Pasta '{pasta.name}' preservada: o nome não é de job, "
                    f"então foi criada por alguém de propósito."
                )
                continue
            bytes_liberados += _tamanho(pasta)
            pastas += 1
            if not dry_run:
                shutil.rmtree(pasta, ignore_errors=True)

    return len(orfas), pastas, bytes_liberados


async def faxina(db: AsyncSession, dry_run: bool = False) -> FaxinaResultado:
    """Passada completa de retenção."""
    r = FaxinaResultado()
    r.clipes_expirados, r.bytes_de_clipes = await expirar_clipes(db, dry_run)
    r.downloads_apagados, r.bytes_de_downloads = await apagar_downloads(db, dry_run)
    r.transcricoes_orfas, r.pastas_orfas, r.bytes_orfaos = await limpar_orfaos(
        db, dry_run
    )
    return r
