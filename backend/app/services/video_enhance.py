"""
Pós-processamento do vídeo bruto do Veo: upscale → interpolação → reencode.

O bruto sai em 720p/24fps com bitrate baixo. As três etapas rodam em sequência,
cada uma gravando um arquivo próprio, e o resultado de cada etapa é a entrada da
seguinte.

Duas regras de robustez, porque isto roda desatendido:

1. **Nenhuma etapa é obrigatória.** Se uma falhar, o vídeo da etapa anterior
   segue como entrada da próxima e o job termina com aviso — em vez de perder um
   vídeo que já foi pago para o Google gerar.
2. **Cada etapa tem uma ferramenta preferida e um plano B em FFmpeg.**
   Real-ESRGAN e RIFE dão resultado melhor, mas são binários externos que podem
   não estar instalados (ou quebrar); o FFmpeg puro sempre está lá, já que o
   resto do ClipMint depende dele.
"""

import asyncio
import json
import logging
import shutil
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Awaitable, Callable

from app.config import settings

logger = logging.getLogger(__name__)


class EnhanceStepError(RuntimeError):
    """Uma etapa falhou. Não é fatal: o pipeline segue com o arquivo anterior."""


class StepNotNeeded(EnhanceStepError):
    """A etapa não tinha o que fazer (a fonte já está no alvo).

    Separado de uma falha de verdade porque a UI trata os dois de formas
    opostas: falha vira alerta âmbar de "parte do processamento não rodou",
    enquanto isto é o resultado correto e não merece alarme nenhum.
    """


@dataclass
class VideoInfo:
    width: int
    height: int
    fps: float
    has_audio: bool

    @property
    def short_side(self) -> int:
        return min(self.width, self.height)


@dataclass
class EnhanceResult:
    """Resultado do pós-processamento."""

    path: Path
    steps_done: list[str] = field(default_factory=list)
    # Etapas que não tinham o que fazer. Não são problema — ficam fora de
    # `warnings` para não virarem alerta na tela.
    skipped: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def fully_enhanced(self) -> bool:
        return not self.warnings


# ── Utilitários de processo ───────────────────────────────────────────────────

def _run(cmd: list[str], timeout: int | None = None) -> None:
    """Roda um comando externo e transforma falha em EnhanceStepError legível."""
    timeout = timeout or settings.enhance_step_timeout
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        raise EnhanceStepError(f"{Path(cmd[0]).name} passou de {timeout}s e foi abortado")
    except FileNotFoundError:
        raise EnhanceStepError(f"binário não encontrado: {cmd[0]}")

    if proc.returncode != 0:
        # O FFmpeg despeja o log inteiro no stderr; as últimas linhas é que
        # dizem o que quebrou.
        tail = [ln for ln in (proc.stderr or "").strip().splitlines() if ln.strip()][-3:]
        raise EnhanceStepError(" | ".join(tail) or f"{Path(cmd[0]).name} saiu com código {proc.returncode}")


def probe(path: Path) -> VideoInfo:
    """Dimensões, fps e presença de áudio. Levanta EnhanceStepError se ilegível."""
    cmd = [
        "ffprobe", "-v", "error", "-print_format", "json",
        "-show_streams", "-select_streams", "v:0", str(path),
    ]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
    except (subprocess.TimeoutExpired, FileNotFoundError) as e:
        raise EnhanceStepError(f"ffprobe indisponível ou travado: {e}")
    if proc.returncode != 0:
        raise EnhanceStepError(f"ffprobe não leu o vídeo: {(proc.stderr or '').strip()[:200]}")

    streams = (json.loads(proc.stdout or "{}")).get("streams") or []
    if not streams:
        raise EnhanceStepError("o arquivo não tem stream de vídeo")
    v = streams[0]

    # avg_frame_rate vem como fração ("24/1"); "0/0" acontece em stream sem
    # duração conhecida, daí o fallback.
    fps = 24.0
    raw_fps = v.get("avg_frame_rate") or v.get("r_frame_rate") or ""
    if "/" in raw_fps:
        num, _, den = raw_fps.partition("/")
        try:
            if float(den) > 0:
                fps = float(num) / float(den)
        except ValueError:
            pass

    audio = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "a:0", "-show_entries",
         "stream=codec_type", "-of", "csv=p=0", str(path)],
        capture_output=True, text=True, timeout=60,
    )
    return VideoInfo(
        width=int(v.get("width") or 0),
        height=int(v.get("height") or 0),
        fps=fps or 24.0,
        has_audio="audio" in (audio.stdout or ""),
    )


def _audio_args(info: VideoInfo, final: bool = False) -> list[str]:
    """Nos intermediários o áudio é copiado; no final é reencodado uma vez só."""
    if not info.has_audio:
        return ["-an"]
    return ["-c:a", "aac", "-b:a", "192k"] if final else ["-c:a", "copy"]


# ── Etapa 1: upscale ──────────────────────────────────────────────────────────

def _upscale_ffmpeg(src: Path, dst: Path, info: VideoInfo, target: int) -> None:
    """Lanczos + unsharp: não inventa detalhe, mas não deixa a imagem macia.

    Escala pelo lado MENOR para funcionar igual em vertical e horizontal —
    720x1280 vira 1080x1920, e 1280x720 vira 1920x1080.
    """
    if info.width <= info.height:
        scale = f"scale={target}:-2:flags=lanczos"
    else:
        scale = f"scale=-2:{target}:flags=lanczos"
    sharpen = f",unsharp=5:5:{settings.enhance_sharpen}:5:5:0.0" if settings.enhance_sharpen > 0 else ""
    _run([
        "ffmpeg", "-y", "-v", "error", "-i", str(src),
        "-vf", scale + sharpen,
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "16", "-pix_fmt", "yuv420p",
        *_audio_args(info), str(dst),
    ])


def _upscale_realesrgan(src: Path, dst: Path, info: VideoInfo, target: int, binary: str) -> None:
    """Real-ESRGAN quadro a quadro (o binário ncnn só processa imagens).

    Ele só amplia em fatores inteiros, então vai a 2x e o FFmpeg reduz para a
    altura alvo — reduzir depois de ampliar preserva mais detalhe que ampliar
    direto para 1.5x.
    """
    with tempfile.TemporaryDirectory(prefix="esrgan_", dir=str(dst.parent)) as tmp:
        tmpdir = Path(tmp)
        raw_frames, up_frames = tmpdir / "in", tmpdir / "out"
        raw_frames.mkdir()
        up_frames.mkdir()

        _run(["ffmpeg", "-y", "-v", "error", "-i", str(src), str(raw_frames / "%08d.png")])
        if not any(raw_frames.iterdir()):
            raise EnhanceStepError("nenhum frame extraído para o upscale")

        _run([binary, "-i", str(raw_frames), "-o", str(up_frames),
              "-n", "realesr-animevideov3", "-s", "2", "-f", "png"])
        if not any(up_frames.iterdir()):
            raise EnhanceStepError("o Real-ESRGAN não produziu frames")

        scale = f"scale={target}:-2:flags=lanczos" if info.width <= info.height \
            else f"scale=-2:{target}:flags=lanczos"
        # Remonta com os frames ampliados e traz o áudio do original.
        cmd = [
            "ffmpeg", "-y", "-v", "error",
            "-framerate", f"{info.fps:.6f}", "-i", str(up_frames / "%08d.png"),
            "-i", str(src),
            "-map", "0:v:0",
        ]
        if info.has_audio:
            cmd += ["-map", "1:a:0", "-c:a", "copy"]
        else:
            cmd += ["-an"]
        cmd += ["-vf", scale, "-c:v", "libx264", "-preset", "veryfast", "-crf", "16",
                "-pix_fmt", "yuv420p", str(dst)]
        _run(cmd)


def upscale(src: Path, dst: Path, info: VideoInfo) -> str:
    """Leva o lado menor até a altura alvo. Devolve o nome da ferramenta usada."""
    target = settings.enhance_target_height
    if info.short_side >= target:
        raise StepNotNeeded(f"já está em {info.width}x{info.height}")

    binary = shutil.which("realesrgan-ncnn-vulkan") or shutil.which("realesrgan")
    if binary:
        try:
            _upscale_realesrgan(src, dst, info, target, binary)
            return "Real-ESRGAN"
        except EnhanceStepError as e:
            # Cai para o FFmpeg em vez de abrir mão do upscale: o binário pode
            # estar instalado mas sem driver Vulkan funcionando.
            logger.warning(f"Real-ESRGAN falhou ({e}); usando lanczos do FFmpeg")

    _upscale_ffmpeg(src, dst, info, target)
    return "FFmpeg lanczos"


# ── Etapa 2: interpolação de frames ───────────────────────────────────────────

def _interpolate_ffmpeg(src: Path, dst: Path, info: VideoInfo, fps: int) -> None:
    """minterpolate com compensação de movimento.

    É a etapa mais cara do pipeline (estima movimento bloco a bloco, em CPU),
    mas é a única que gera quadros novos de verdade — `fps=` sozinho só
    duplicaria quadros, sem ganho nenhum de fluidez.
    """
    _run([
        "ffmpeg", "-y", "-v", "error", "-i", str(src),
        "-vf", f"minterpolate=fps={fps}:mi_mode=mci:mc_mode=aobmc:me_mode=bidir:vsbmc=1",
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "16", "-pix_fmt", "yuv420p",
        *_audio_args(info), str(dst),
    ])


def _interpolate_rife(src: Path, dst: Path, info: VideoInfo, fps: int, binary: str) -> None:
    """RIFE quadro a quadro. Dobra a contagem de frames (24→48)."""
    with tempfile.TemporaryDirectory(prefix="rife_", dir=str(dst.parent)) as tmp:
        tmpdir = Path(tmp)
        raw_frames, out_frames = tmpdir / "in", tmpdir / "out"
        raw_frames.mkdir()
        out_frames.mkdir()

        _run(["ffmpeg", "-y", "-v", "error", "-i", str(src), str(raw_frames / "%08d.png")])
        n_in = len(list(raw_frames.iterdir()))
        if not n_in:
            raise EnhanceStepError("nenhum frame extraído para a interpolação")

        # -n = quantos frames o RIFE deve produzir no total.
        _run([binary, "-i", str(raw_frames), "-o", str(out_frames), "-n", str(n_in * 2)])
        if not any(out_frames.iterdir()):
            raise EnhanceStepError("o RIFE não produziu frames")

        cmd = [
            "ffmpeg", "-y", "-v", "error",
            "-framerate", str(fps), "-i", str(out_frames / "%08d.png"),
            "-i", str(src), "-map", "0:v:0",
        ]
        if info.has_audio:
            cmd += ["-map", "1:a:0", "-c:a", "copy"]
        else:
            cmd += ["-an"]
        cmd += ["-c:v", "libx264", "-preset", "veryfast", "-crf", "16",
                "-pix_fmt", "yuv420p", str(dst)]
        _run(cmd)


def interpolate(src: Path, dst: Path, info: VideoInfo) -> str:
    """Sobe o framerate até o alvo. Devolve o nome da ferramenta usada."""
    fps = settings.enhance_target_fps
    if info.fps >= fps - 0.5:
        raise StepNotNeeded(f"já está em {info.fps:.0f}fps")

    binary = shutil.which("rife-ncnn-vulkan") or shutil.which("rife")
    if binary:
        try:
            _interpolate_rife(src, dst, info, fps, binary)
            return "RIFE"
        except EnhanceStepError as e:
            logger.warning(f"RIFE falhou ({e}); usando minterpolate do FFmpeg")

    _interpolate_ffmpeg(src, dst, info, fps)
    return "FFmpeg minterpolate"


# ── Etapa 3: reencode final ───────────────────────────────────────────────────

def reencode(src: Path, dst: Path, info: VideoInfo) -> str:
    """H.264 com bitrate alvo, yuv420p, áudio preservado.

    `maxrate`/`bufsize` prendem os picos: sem eles o x264 estoura muito acima do
    alvo em cenas de movimento e o arquivo fica difícil de subir.
    """
    bitrate = settings.enhance_video_bitrate
    _run([
        "ffmpeg", "-y", "-v", "error", "-i", str(src),
        "-c:v", "libx264", "-preset", "medium",
        "-b:v", bitrate, "-maxrate", bitrate, "-bufsize", f"{_double_bitrate(bitrate)}",
        "-pix_fmt", "yuv420p", "-movflags", "+faststart",
        *_audio_args(info, final=True), str(dst),
    ])
    return f"H.264 {bitrate}"


def _double_bitrate(bitrate: str) -> str:
    """'12M' → '24M'. bufsize do dobro do alvo é a recomendação usual do x264."""
    try:
        return f"{int(bitrate.rstrip('Mm')) * 2}M"
    except ValueError:
        return bitrate


# ── Orquestração ──────────────────────────────────────────────────────────────

StepCallback = Callable[[str], Awaitable[None]]


async def run_enhancement(
    raw_path: Path, work_dir: Path, on_step: StepCallback | None = None
) -> EnhanceResult:
    """
    Roda as três etapas sobre `raw_path` e devolve o melhor vídeo conseguido.

    `on_step` é chamado antes de cada etapa com o texto que vai para
    `status_detail` — é o que faz a UI mostrar "fazendo upscale" em vez de ficar
    parada em "postprocessing" por vários minutos.

    Nunca levanta por falha de etapa: o pior caso devolve o próprio `raw_path`
    com os avisos do que não deu certo.
    """
    work_dir.mkdir(parents=True, exist_ok=True)
    result = EnhanceResult(path=raw_path)

    try:
        info = await asyncio.to_thread(probe, raw_path)
    except EnhanceStepError as e:
        # Sem ffprobe não dá para decidir nada; devolve o bruto intacto.
        result.warnings.append(f"não consegui analisar o vídeo bruto ({e})")
        return result

    logger.info(
        f"Pós-processamento: entrada {info.width}x{info.height} @ {info.fps:.1f}fps "
        f"(áudio: {'sim' if info.has_audio else 'não'})"
    )

    stages: list[tuple[str, str, Callable[[Path, Path, VideoInfo], str]]] = [
        ("upscale", "fazendo upscale", upscale),
        ("interpolate", "interpolando frames", interpolate),
        ("reencode", "reencodando", reencode),
    ]

    current = raw_path
    for key, label, fn in stages:
        if on_step:
            await on_step(label)
        dst = work_dir / f"{raw_path.stem}_{key}.mp4"
        try:
            tool = await asyncio.to_thread(fn, current, dst, info)
        except StepNotNeeded as e:
            result.skipped.append(f"{label}: {e}")
            logger.info(f"Etapa '{key}' dispensada: {e}")
            continue
        except EnhanceStepError as e:
            result.warnings.append(f"{label}: {e}")
            logger.warning(f"Etapa '{key}' pulada: {e}")
            continue
        except Exception as e:  # noqa: BLE001 — etapa nenhuma pode derrubar o job
            result.warnings.append(f"{label}: erro inesperado ({e})")
            logger.exception(f"Etapa '{key}' quebrou de forma inesperada")
            continue

        if not dst.exists() or dst.stat().st_size == 0:
            result.warnings.append(f"{label}: saída vazia, etapa descartada")
            continue

        # Só relê o arquivo se a etapa mudou dimensões/fps — o reencode não muda.
        if key in ("upscale", "interpolate"):
            try:
                info = await asyncio.to_thread(probe, dst)
            except EnhanceStepError:
                pass  # segue com a info anterior; as próximas etapas toleram

        result.steps_done.append(f"{label} ({tool})")
        current = dst

    result.path = current
    logger.info(
        f"Pós-processamento concluído: {current.name} "
        f"[{', '.join(result.steps_done) or 'nenhuma etapa aplicada'}]"
    )
    return result
