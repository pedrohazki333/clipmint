import asyncio
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import yt_dlp

from app.utils import ytdlp as ytdlp_opts

from app.config import settings
from app.utils.ffmpeg import get_duration, run_ffmpeg

logger = logging.getLogger(__name__)

# Áudio e vídeo saem do MESMO arquivo: num merge são a diferença entre eles
# fica na casa dos milissegundos (medido: 7ms em jobs saudáveis). 1s é folga de
# sobra e ainda pega qualquer desalinhamento capaz de deslocar um corte.
_AV_DRIFT_TOLERANCE = 1.0

# O YouTube informa a duração em segundos inteiros, então a comparação com o
# arquivo baixado é mais grosseira — serve para pegar download truncado.
_TRUNCATION_TOLERANCE = 2.0
_TRUNCATION_RATIO = 0.005


class MediaIntegrityError(RuntimeError):
    """O vídeo baixado não serve: truncado, ou com áudio fora do vídeo."""


@dataclass
class VideoMetadata:
    title: str
    channel: str
    duration: float
    thumbnail_url: Optional[str]
    video_path: str
    audio_path: str


# Erros que NUNCA passam por esperar: o vídeo não existe, é privado, exige
# login, tem DRM. Retentar nesses casos só faz o job demorar minutos para
# entregar a mesma resposta, e esconde do usuário qual é o problema de verdade.
_PERMANENT_ERRORS = (
    "video unavailable",
    "private video",
    "removed by the uploader",
    "account associated with this video has been terminated",
    "drm protected",
    "sign in to confirm your age",
    "join this channel",
    "members-only",
    "is not available in your country",
    "requested format is not available",
    "unsupported url",
    "incomplete youtube id",
)

# Tentativas do download inteiro, cada uma re-extraindo a URL do zero. É isso
# que cura o 403 do YouTube: a URL do googlevideo é assinada e a assinatura é
# que caduca — baixar de novo com a MESMA URL não adianta, extrair outra sim.
_DOWNLOAD_ATTEMPTS = 5
# Espera antes de cada nova tentativa. Nos casos observados o bloqueio passou
# em segundos ou poucos minutos, então a escada cobre bem sem pendurar o job.
_DOWNLOAD_BACKOFF = (10, 30, 90, 240)


def _is_permanent(message: str) -> bool:
    """Se insistir neste erro é perda de tempo."""
    lowered = message.lower()
    return any(marker in lowered for marker in _PERMANENT_ERRORS)


def _download_sync(youtube_url: str, video_path: str) -> dict:
    """Baixa o vídeo com yt-dlp (bloqueante — executar fora do event loop)."""
    # Até 4K: o crop 9:16 usa só ~56% da largura do vídeo — fonte 1080p vira
    # upscale no clip final. Com fonte 2160p o crop sai em resolução nativa.
    ydl_opts = {
        # Mesma autenticação da consulta de metadados (ver utils/ytdlp.py).
        **ytdlp_opts.base_opts(),
        "format": "bestvideo[height<=2160]+bestaudio/bestvideo[height<=2160]/best[height<=2160]/best",
        "outtmpl": video_path,
        "merge_output_format": "mp4",
        # Retentativas DENTRO de uma tentativa, para o soluço curto não custar
        # uma re-extração inteira. A camada de fora cuida do resto.
        "retries": 10,
        "fragment_retries": 10,
        "extractor_retries": 3,
        "file_access_retries": 5,
        # Pedidos em pedaços: o YouTube corta transferência longa de uma vez só,
        # e em pedaços o que falha é o pedaço, que o "retries" acima refaz.
        "http_chunk_size": 10 * 1024 * 1024,
        "continuedl": True,
    }
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        return ydl.extract_info(youtube_url, download=True)


async def _download_with_retry(job_id: str, youtube_url: str, video_path: str) -> dict:
    """
    Baixa o vídeo, insistindo enquanto o erro for do tipo que passa sozinho.

    O YouTube derruba download com `HTTP Error 403: Forbidden` de tempos em
    tempos, sem nada de errado no vídeo nem na ferramenta: em três casos
    observados em 18/08/2026 o MESMO vídeo baixou inteiro minutos depois. Sem
    esta camada cada um desses soluços marcava o job como erro e alguém tinha
    que mandar rodar de novo à mão.

    Cada tentativa re-extrai a URL do zero, que é o que realmente resolve — a
    URL do googlevideo é assinada e o que caduca é a assinatura.

    Erro permanente (vídeo privado, removido, com DRM) não é retentado: a
    resposta seria a mesma e o usuário merece saber logo.
    """
    for attempt in range(1, _DOWNLOAD_ATTEMPTS + 1):
        try:
            return await asyncio.to_thread(_download_sync, youtube_url, video_path)
        except yt_dlp.utils.DownloadError as exc:
            message = str(exc)
            if _is_permanent(message):
                logger.error(f"[{job_id}] Download impossível: {message}")
                raise
            if attempt == _DOWNLOAD_ATTEMPTS:
                logger.error(
                    f"[{job_id}] Download falhou em {_DOWNLOAD_ATTEMPTS} tentativas"
                )
                raise
            espera = _DOWNLOAD_BACKOFF[attempt - 1]
            logger.warning(
                f"[{job_id}] Download falhou (tentativa {attempt}/"
                f"{_DOWNLOAD_ATTEMPTS}): {message.strip()[:160]} — "
                f"nova tentativa em {espera}s"
            )
            await asyncio.sleep(espera)

    raise RuntimeError("inalcançável")  # pragma: no cover


async def _extract_audio(job_id: str, video_path: str, audio_path: str) -> None:
    """Extrai o áudio do vídeo local (WAV mono 16kHz, o que a transcrição usa)."""
    logger.info(f"[{job_id}] Extracting audio...")
    await run_ffmpeg(
        "-i", video_path,
        "-vn",
        "-acodec", "pcm_s16le",
        "-ar", "16000",
        "-ac", "1",
        audio_path,
        description=f"Extract audio for job {job_id}",
    )
    logger.info(f"[{job_id}] Audio extracted to: {audio_path}")


async def ensure_media(
    job_id: str,
    video_path: str,
    audio_path: str,
    expected_duration: float = 0.0,
) -> bool:
    """
    Garante que o vídeo e o áudio em disco descrevem a MESMA linha do tempo.

    É a checagem mais importante do pipeline: a transcrição é feita sobre o
    áudio, mas os cortes acontecem sobre o vídeo. Se os dois discordam, tudo
    depois disso sai errado de um jeito silencioso — os clips abrem normalmente,
    só mostram o trecho errado, com a legenda fora de sincronia. Um merge
    interrompido (ou dois processos escrevendo no mesmo arquivo) produz
    exatamente isso: pacotes de áudio corrompidos são descartados na
    decodificação e o áudio fica mais curto que o vídeo.

    Quando só o áudio está fora, ele é re-extraído — é barato e resolve
    extração interrompida. Se nem assim bater, o problema está dentro do vídeo.

    Retorna True se a mídia é confiável, False se o vídeo precisa ser baixado
    de novo.
    """
    if not Path(video_path).is_file():
        return False

    try:
        video_duration = await get_duration(video_path)
    except (ValueError, RuntimeError) as exc:
        logger.warning(f"[{job_id}] Vídeo ilegível ({exc})")
        return False

    # Download truncado: o arquivo é menor que o vídeo do YouTube.
    if expected_duration > 0:
        tolerance = max(_TRUNCATION_TOLERANCE, expected_duration * _TRUNCATION_RATIO)
        if abs(expected_duration - video_duration) > tolerance:
            logger.warning(
                f"[{job_id}] Vídeo truncado: {video_duration:.1f}s em disco, "
                f"{expected_duration:.1f}s no YouTube"
            )
            return False

    for extracted in (False, True):
        if Path(audio_path).is_file():
            try:
                audio_duration = await get_duration(audio_path)
            except (ValueError, RuntimeError):
                audio_duration = None
            if audio_duration is not None:
                drift = abs(video_duration - audio_duration)
                if drift <= _AV_DRIFT_TOLERANCE:
                    return True
                logger.warning(
                    f"[{job_id}] Áudio e vídeo fora de sincronia: "
                    f"vídeo {video_duration:.1f}s, áudio {audio_duration:.1f}s "
                    f"(desvio de {drift:.1f}s)"
                )

        if extracted:  # já tentamos re-extrair: o áudio dentro do vídeo é ruim
            return False

        logger.info(f"[{job_id}] Re-extraindo o áudio para conferir de novo")
        Path(audio_path).unlink(missing_ok=True)
        await _extract_audio(job_id, video_path, audio_path)

    return False


def _clear_partial_merge(job_dir: Path) -> None:
    """
    Remove sobra de mesclagem interrompida.

    O yt-dlp mescla vídeo e áudio num `video.temp.mp4` antes de renomear para o
    destino final. Se o processo morreu no meio, esse arquivo fica para trás —
    e um merge novo tem que começar do zero, nunca em cima do anterior.
    """
    for leftover in job_dir.glob("video.temp.*"):
        leftover.unlink(missing_ok=True)


async def download_video(job_id: str, youtube_url: str) -> VideoMetadata:
    """
    Baixa o vídeo do YouTube (uma única vez) e extrai o áudio localmente.

    O download roda em thread separada para não bloquear o event loop —
    downloads longos não podem travar a API enquanto o frontend faz polling.
    O áudio é extraído do arquivo já baixado via FFmpeg (WAV mono 16kHz,
    suficiente para transcrição e muito menor que WAV full quality).
    """
    job_dir = settings.downloads_dir / job_id
    job_dir.mkdir(parents=True, exist_ok=True)

    video_path = str(job_dir / "video.mp4")
    audio_path = str(job_dir / "audio.wav")

    # Se sobrou arquivo de um download anterior, ele não é confiável: o pipeline
    # só chega aqui quando não há mídia boa em disco. E o yt-dlp pula o download
    # quando o destino já existe, então o arquivo ruim tem que sair da frente.
    # Os arquivos parciais (.part, formatos separados) ficam — são eles que
    # deixam um download interrompido continuar de onde parou.
    Path(video_path).unlink(missing_ok=True)
    Path(audio_path).unlink(missing_ok=True)

    for attempt in (1, 2):
        _clear_partial_merge(job_dir)

        logger.info(f"[{job_id}] Downloading video from: {youtube_url}")
        info = await _download_with_retry(job_id, youtube_url, video_path)

        title = info.get("title", "Unknown Title")
        channel = info.get("uploader") or info.get("channel") or "Unknown Channel"
        duration = float(info.get("duration") or 0)
        thumbnail_url = info.get("thumbnail")

        logger.info(f"[{job_id}] Video downloaded: {title} ({duration:.0f}s)")

        # Extrai o áudio do arquivo local — evita baixar o vídeo uma segunda vez
        await _extract_audio(job_id, video_path, audio_path)

        if await ensure_media(job_id, video_path, audio_path, duration):
            break

        # Arquivo ruim: não adianta seguir para a transcrição (custa dinheiro e
        # produziria clips fora de sincronia). Apaga tudo e baixa de novo.
        if attempt == 2:
            raise MediaIntegrityError(
                "O vídeo baixado saiu corrompido nas duas tentativas: o áudio "
                "não acompanha o vídeo. Sem isso os cortes e as legendas sairiam "
                "fora de sincronia, então o job foi interrompido aqui."
            )
        logger.warning(f"[{job_id}] Mídia inconsistente — baixando de novo")
        Path(video_path).unlink(missing_ok=True)
        Path(audio_path).unlink(missing_ok=True)

    return VideoMetadata(
        title=title,
        channel=channel,
        duration=duration,
        thumbnail_url=thumbnail_url,
        video_path=video_path,
        audio_path=audio_path,
    )
