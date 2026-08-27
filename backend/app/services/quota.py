"""
Travas de custo: quanto cada usuário pode processar, e de que tamanho.

Existem por um motivo só: transcrição e análise são cobradas por minuto de
áudio. Sem teto, um bug num laço ou uma pessoa mal-intencionada viram uma
fatura — e o prejuízo aparece dias depois, no cartão, não no log.

Três guardas, todas ANTES de qualquer gasto:

  1. **duração do vídeo** — um teto por vídeo, conferido com uma chamada de
     metadados (barata) antes do download (caro);
  2. **cota por janela** — vídeos E minutos por usuário, em janela deslizante;
  3. **duplicata** — o mesmo link, do mesmo usuário, já em processamento.

Nenhuma delas roda depois do download: recusar um vídeo depois de baixá-lo e
transcrevê-lo já teria custado exatamente o que se queria evitar.
"""

import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import yt_dlp
from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.features import billing_enabled, public_build
from app.models import Job, User
from app.workers.pipeline import RUNNING_STATUSES

logger = logging.getLogger(__name__)


class QuotaExceeded(HTTPException):
    """429: o usuário estourou um teto. A mensagem diz qual e quando alivia."""

    def __init__(self, detail: str) -> None:
        super().__init__(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail=detail)


def max_source_seconds() -> float:
    """Teto de duração de um vídeo, em segundos. 0 = sem teto.

    O build público tem um teto próprio, porque lá quem paga a conta não é quem
    escolhe o vídeo. Na versão pessoal o padrão é sem teto — quem manda o link é
    quem paga por ele.
    """
    minutos = settings.max_source_minutes
    if not minutos and public_build():
        minutos = settings.public_max_source_minutes
    return minutos * 60.0


def quota_limits() -> tuple[int, int]:
    """(vídeos, minutos) permitidos na janela. 0 em qualquer um = desligado.

    **Os padrões do público saem de cena quando há cobrança por crédito.** A cota
    de janela existia como trava de custo enquanto o uso era grátis: sem ela, uma
    pessoa sozinha viraria uma fatura de AssemblyAI e Anthropic. Com saldo, quem
    trava o custo é o saldo — não se processa o que não foi pago — e manter as
    duas significaria recusar trabalho de alguém que PAGOU por ele, o que é pior
    que não ter limite nenhum.

    O que sobrevive é o teto EXPLÍCITO: `QUOTA_MAX_VIDEOS`/`QUOTA_MAX_MINUTES`
    preenchidos continuam valendo mesmo com cobrança, como alavanca de
    emergência para conter abuso sem derrubar o servidor.

    O que continua valendo nas duas versões: o teto de duração por vídeo e a
    recusa de transmissão ao vivo. Essas não são cobrança, são sanidade — a live
    não tem fim previsto e o vídeo de 8 horas quebra o prompt de análise.

    A resposta é uma só para quem barra e para quem mostra na tela: uma segunda
    fórmula viraria uma tela que discorda do que recusa o job.
    """
    videos = settings.quota_max_videos
    minutos = settings.quota_max_minutes

    if billing_enabled():
        # Só os PADRÕES do público saem de cena. O que o operador escreveu
        # explicitamente em QUOTA_MAX_* continua valendo: é a alavanca de
        # emergência para conter um abuso sem ter que derrubar o servidor.
        return videos, minutos

    if public_build():
        videos = videos or settings.public_quota_max_videos
        minutos = minutos or settings.public_quota_max_minutes
    return videos, minutos


def _probe_sync(url: str) -> dict:
    """Metadados do vídeo, sem baixar nada."""
    opts = {
        "quiet": True,
        "no_warnings": True,
        "skip_download": True,
        # Sem isto, um link de playlist faria o yt-dlp enumerar a lista inteira.
        "noplaylist": True,
    }
    with yt_dlp.YoutubeDL(opts) as ydl:
        return ydl.extract_info(url, download=False) or {}


@dataclass
class Metadados:
    """O que a consulta ao YouTube diz sobre o vídeo, antes de baixá-lo."""

    duration: float = 0.0
    #: Transmissão AO VIVO acontecendo agora. Não tem duração, e por isso
    #: escapava do teto: o job era aceito e o yt-dlp começava a GRAVAR a live,
    #: sem fim previsto. Descoberto testando o teto com um link de live real.
    is_live: bool = False
    #: A consulta respondeu? False = não sabemos NADA sobre este vídeo, o que é
    #: diferente de "sabemos que não tem duração".
    ok: bool = False


async def probe(url: str) -> Metadados:
    """
    Metadados do vídeo, sem baixá-lo.

    É uma chamada de metadados — segundos, não os minutos de um download. É o
    que permite recusar um vídeo de 8 horas antes de gastar banda e API.

    Falha de rede aqui NÃO impede a criação do job: a alternativa seria recusar
    trabalho legítimo por um soluço momentâneo, e o download logo à frente vai
    tropeçar no mesmo problema com uma mensagem melhor. O que se perde é a
    conferência do teto neste job — registrado no log.
    """
    try:
        info = await asyncio.wait_for(
            asyncio.to_thread(_probe_sync, url), timeout=settings.probe_timeout
        )
    except asyncio.TimeoutError:
        logger.warning(f"Consulta de metadados passou de {settings.probe_timeout}s: {url}")
        return Metadados()
    except yt_dlp.utils.DownloadError as exc:
        # Vídeo privado, removido, com DRM: o erro é do vídeo, não da rede, e
        # vale recusar já — o download daria o mesmo resultado minutos depois.
        from app.errors import user_message
        from app.services.downloader import _is_permanent

        if _is_permanent(str(exc)):
            raise HTTPException(status_code=422, detail=user_message(exc)) from exc
        logger.warning(f"Não foi possível consultar os metadados de {url}: {exc}")
        return Metadados()
    except Exception as exc:  # noqa: BLE001 - metadado é conveniência, não requisito
        logger.warning(f"Consulta de metadados falhou ({type(exc).__name__}): {exc}")
        return Metadados()

    return Metadados(
        duration=float(info.get("duration") or 0),
        # `is_live` é o que está no ar AGORA; `was_live` é a gravação de uma
        # live que já terminou, e essa tem duração e é material legítimo.
        # `live_status` cobre também a live AGENDADA, que ainda nem começou.
        is_live=bool(info.get("is_live"))
        or info.get("live_status") in ("is_live", "is_upcoming"),
        ok=True,
    )


def check_live(meta: "Metadados") -> None:
    """Recusa transmissão ao vivo.

    Live não tem duração, então escapa do teto — e o yt-dlp, apontado para uma,
    começa a GRAVÁ-LA sem fim previsto: disco, banda e minutos de transcrição
    crescendo enquanto a transmissão durar. Foi assim que este caso apareceu,
    testando o teto de duração com um link de live real.

    A recusa vale nas duas versões: não é questão de quem paga, é que o produto
    não sabe fazer isso. Gravação de live que já terminou (`was_live`) tem
    duração e passa normalmente.
    """
    if not meta.is_live:
        return
    raise HTTPException(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        detail=(
            "Este link é de uma transmissão ao vivo em andamento, que não tem "
            "duração definida. Espere a live acabar e use o link da gravação."
        ),
    )


def check_duration(meta: "Metadados") -> None:
    """Recusa vídeo acima do teto — e, no público, também o de duração incerta.

    Este segundo caso é a lição mais cara desta fatia. A primeira versão deixava
    passar quando a consulta de metadados falhava, com o raciocínio de que um
    soluço de rede não devia recusar trabalho legítimo. Só que a consulta e o
    download falham por motivos DIFERENTES: num teste real, o link de uma live
    devolveu "This live stream recording is not available" na consulta e baixou
    normalmente logo em seguida — **18 GB** antes de alguém perceber.

    Ou seja: o caminho de escape do guarda de custo era justamente o caminho que
    o vídeo caro percorria. Guarda de custo tem que falhar FECHADO.

    Na versão pessoal segue permissivo: lá não há teto por padrão, quem manda o
    link paga por ele, e recusar por um soluço de rede só atrapalharia.
    """
    teto = max_source_seconds()
    if not teto:
        return

    if not meta.ok or not meta.duration:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                "Não foi possível descobrir a duração deste vídeo, e há um "
                "limite de tamanho — então ele não pode ser aceito. Confira se "
                "o link está certo e se o vídeo é público."
            ),
        )

    if meta.duration <= teto:
        return

    raise HTTPException(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        detail=(
            f"Este vídeo tem {meta.duration / 60:.0f} minutos e o limite é "
            f"{teto / 60:.0f}. Corte um trecho menor ou use um vídeo mais curto."
        ),
    )


async def check_duplicate(db: AsyncSession, user: User, url: str) -> None:
    """
    Recusa o mesmo link que já está sendo processado por esta pessoa.

    Dois cliques no botão custavam dois downloads e duas transcrições do MESMO
    vídeo. Só barra o que está em andamento: reprocessar um vídeo já concluído é
    pedido legítimo (mudou o preset, mudou o modo de legenda).
    """
    existente = (
        await db.execute(
            select(Job.id).where(
                Job.user_id == user.id,
                Job.youtube_url == url,
                Job.status.in_(RUNNING_STATUSES),
            )
        )
    ).scalar_one_or_none()

    if existente:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "Este vídeo já está sendo processado. Acompanhe o andamento em "
                "vez de começar de novo — o job é o mesmo."
            ),
        )


async def check_quota(db: AsyncSession, user: User, duration_seconds: float) -> None:
    """
    Recusa quem estourou a cota da janela.

    Os dois tetos valem ao mesmo tempo e o que estourar primeiro barra: dez
    vídeos de duas horas custam vinte vezes mais que dez de seis minutos, então
    contar só a quantidade não protegeria a conta.

    A janela é deslizante. Com "por dia", quem estoura às 23h volta a ter tudo
    às 00h, e o pico de abuso cabe em duas horas.
    """
    max_videos, max_minutos = quota_limits()
    if not max_videos and not max_minutos:
        return

    inicio = datetime.now(timezone.utc) - timedelta(hours=settings.quota_window_hours)
    linha = (
        await db.execute(
            select(
                func.count(Job.id),
                func.coalesce(func.sum(Job.duration_seconds), 0.0),
            ).where(Job.user_id == user.id, Job.created_at >= inicio)
        )
    ).one()
    videos, segundos = int(linha[0] or 0), float(linha[1] or 0.0)

    janela = f"{settings.quota_window_hours}h"

    if max_videos and videos >= max_videos:
        raise QuotaExceeded(
            f"Você já processou {videos} vídeos nas últimas {janela}, que é o "
            f"limite. Tente de novo mais tarde."
        )

    if max_minutos:
        minutos_usados = segundos / 60.0
        minutos_novo = duration_seconds / 60.0
        if minutos_usados + minutos_novo > max_minutos:
            restante = max(0.0, max_minutos - minutos_usados)
            raise QuotaExceeded(
                f"Você já processou {minutos_usados:.0f} minutos de vídeo nas "
                f"últimas {janela} e o limite é {max_minutos}. "
                + (
                    f"Ainda cabem {restante:.0f} minutos, e este vídeo tem "
                    f"{minutos_novo:.0f}."
                    if restante >= 1
                    else "Tente de novo mais tarde."
                )
            )


async def usage(db: AsyncSession, user: User) -> dict:
    """
    Quanto desta janela a pessoa já gastou — para a tela de conta.

    É a MESMA contagem de `check_quota`, e é de propósito: uma segunda fórmula
    para mostrar na tela viraria uma tela que discorda do que barra o job.
    Teto 0 significa "sem teto" e chega assim ao frontend, que decide como
    mostrar.
    """
    max_videos, max_minutos = quota_limits()
    inicio = datetime.now(timezone.utc) - timedelta(hours=settings.quota_window_hours)
    linha = (
        await db.execute(
            select(
                func.count(Job.id),
                func.coalesce(func.sum(Job.duration_seconds), 0.0),
            ).where(Job.user_id == user.id, Job.created_at >= inicio)
        )
    ).one()
    return {
        "window_hours": settings.quota_window_hours,
        "videos_used": int(linha[0] or 0),
        "videos_max": max_videos,
        "minutes_used": round(float(linha[1] or 0.0) / 60.0, 1),
        "minutes_max": max_minutos,
        "max_source_minutes": int(max_source_seconds() // 60),
    }


async def guard_new_job(db: AsyncSession, user: User, url: str) -> float:
    """
    Todas as guardas, na ordem do mais barato para o mais caro.

    Devolve a duração medida, para o job já nascer com ela — assim a cota do
    próximo pedido conta este vídeo mesmo antes de o download terminar. Sem
    isso, dez pedidos disparados juntos passariam todos, porque nenhum teria
    duração registrada ainda.
    """
    await check_duplicate(db, user, url)
    meta = await probe(url)
    check_live(meta)
    check_duration(meta)
    await check_quota(db, user, meta.duration)
    return meta.duration
