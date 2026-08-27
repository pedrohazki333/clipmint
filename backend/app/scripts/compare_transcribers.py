"""
Roda o mesmo áudio pelos dois provedores e mostra o resultado lado a lado.

É a ferramenta da decisão "trocar ou não o provedor padrão". Não é rota da API
nem passo do pipeline de propósito: rodar dois provedores custa o dobro, e isso
tem que ser um ato deliberado de quem está avaliando, nunca algo que aconteça
por acidente num job comum.

Uso:

    cd backend
    # a partir de um job já baixado (não re-baixa nem re-extrai áudio):
    .venv/bin/python -m app.scripts.compare_transcribers <job_id>

    # a partir de um arquivo de áudio qualquer:
    .venv/bin/python -m app.scripts.compare_transcribers --audio /caminho/audio.wav

    # só um subconjunto dos provedores:
    .venv/bin/python -m app.scripts.compare_transcribers <job_id> --providers deepgram

O relatório sai no terminal e fica salvo em
`storage/comparisons/<nome>_<carimbo>.md`, junto de um JSON de palavras por
provedor — o texto inteiro é longo demais para ser julgado só no terminal.
"""

import argparse
import asyncio
import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import select

from app.config import settings
from app.database import AsyncSessionLocal
from app.models import Job
from app.services.transcription import PROVIDERS, get_provider
from app.services.transcription.compare import render_report, run_provider
from app.utils.ffmpeg import get_duration

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger("compare")


async def _audio_do_job(job_id: str) -> tuple[str, str]:
    """(caminho do áudio, rótulo) a partir de um job já baixado."""
    async with AsyncSessionLocal() as db:
        job = (await db.execute(select(Job).where(Job.id == job_id))).scalar_one_or_none()
    if not job:
        raise SystemExit(f"Job {job_id} não existe.")
    if not job.audio_path or not Path(job.audio_path).is_file():
        raise SystemExit(
            f"O job {job_id} não tem áudio em disco. Rode o pipeline até a "
            f"transcrição pelo menos uma vez, ou passe --audio."
        )
    return job.audio_path, (job.video_title or job_id)[:60]


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("job_id", nargs="?", help="Job já baixado a usar como fonte")
    parser.add_argument("--audio", help="Caminho de um arquivo de áudio")
    parser.add_argument(
        "--providers",
        default=",".join(sorted(PROVIDERS)),
        help="Lista separada por vírgula (padrão: todos)",
    )
    args = parser.parse_args()

    if not args.job_id and not args.audio:
        parser.error("informe um job_id ou --audio")

    if args.audio:
        audio_path, rotulo = args.audio, Path(args.audio).stem
        if not Path(audio_path).is_file():
            raise SystemExit(f"Áudio não encontrado: {audio_path}")
    else:
        audio_path, rotulo = await _audio_do_job(args.job_id)

    duration = await get_duration(audio_path)

    nomes = [n.strip().lower() for n in args.providers.split(",") if n.strip()]
    provedores = []
    for nome in nomes:
        p = get_provider(nome)
        if not p.is_configured():
            logger.warning(
                f"Provedor '{nome}' sem chave de API no .env — será pulado. "
                f"(Configure e rode de novo para incluí-lo na comparação.)"
            )
            continue
        provedores.append(p)

    if not provedores:
        raise SystemExit(
            "Nenhum provedor configurado. Defina ASSEMBLYAI_API_KEY e/ou "
            "DEEPGRAM_API_KEY no .env da raiz."
        )

    saida = Path(settings.storage_dir) / "comparisons"
    saida.mkdir(parents=True, exist_ok=True)
    carimbo = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")

    logger.info(
        f"Comparando {len(provedores)} provedor(es) em {duration / 60:.1f} min de "
        f"áudio: {', '.join(p.name for p in provedores)}"
    )
    logger.info(
        "Cada provedor é cobrado por esta execução — é o preço de decidir com dado."
    )

    # Em sequência, e não em paralelo: o tempo de processamento é uma das
    # medidas, e duas transcrições disputando rede e CPU mediriam a disputa.
    runs = []
    for p in provedores:
        run = await run_provider(p, f"cmp_{carimbo}", audio_path, duration)
        estado = f"{run.elapsed:.1f}s" if run.ok else f"FALHOU ({run.error[:120]})"
        logger.info(f"  {p.name}: {estado}")
        runs.append(run)

        if run.ok:
            palavras = saida / f"{rotulo}_{carimbo}_{p.name}_words.json"
            palavras.write_text(
                json.dumps(
                    [
                        {"text": w.text, "start": w.start, "end": w.end,
                         "confidence": w.confidence}
                        for w in run.words
                    ],
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )

    relatorio = render_report(runs, audio_path, duration)
    destino = saida / f"{rotulo}_{carimbo}.md"
    destino.write_text(relatorio, encoding="utf-8")

    print()
    print(relatorio)
    print()
    logger.info(f"Relatório salvo em {destino}")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        sys.exit(130)
