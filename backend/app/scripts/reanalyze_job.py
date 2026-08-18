"""
Reanalisa um vídeo já baixado, com a rubrica atual.

    cd backend && .venv/bin/python -m app.scripts.reanalyze_job <job_id>

O retry normal (POST /api/jobs/<id>/retry) preserva a análise: ele existe para
terminar o que faltou, não para repensar os cortes. Quando o que mudou foi o
critério — prompt novo, exemplos validados novos, a leitura de áudio dos
buracos da transcrição —, os clips antigos precisam sair da frente para a
análise rodar de novo.

O que é jogado fora: os clips escolhidos pela análise anterior e os arquivos
renderizados deles. O que é preservado: o vídeo, o áudio e a transcrição — ou
seja, não há re-download nem nova cobrança da AssemblyAI. O único custo é a
chamada de análise ao Claude.
"""

import asyncio
import logging
import shutil
import sys

from sqlalchemy import delete, select

from app.config import settings
from app.database import AsyncSessionLocal
from app.models import Clip, Job
from app.workers import joblock
from app.workers.pipeline import run_pipeline


async def _discard_analysis(job_id: str) -> int:
    """Apaga os clips da análise anterior. Devolve quantos eram."""
    async with AsyncSessionLocal() as db:
        result = await db.execute(select(Clip).where(Clip.job_id == job_id))
        count = len(result.scalars().all())
        await db.execute(delete(Clip).where(Clip.job_id == job_id))
        await db.commit()

    shutil.rmtree(settings.clips_dir / job_id, ignore_errors=True)
    return count


async def _job_exists(job_id: str) -> bool:
    async with AsyncSessionLocal() as db:
        result = await db.execute(select(Job).where(Job.id == job_id))
        return result.scalar_one_or_none() is not None


async def _run(job_id: str) -> None:
    if not await _job_exists(job_id):
        print(f"Job {job_id} não existe.", file=sys.stderr)
        raise SystemExit(1)

    discarded = await _discard_analysis(job_id)
    logging.info(f"[{job_id}] {discarded} clip(s) da análise anterior descartados")

    await run_pipeline(job_id, resume=True)


def main() -> None:
    if len(sys.argv) != 2:
        print(__doc__.strip(), file=sys.stderr)
        raise SystemExit(2)

    job_id = sys.argv[1]

    # Mesma guarda do resume_job: dois processos no mesmo job corrompem os
    # arquivos um do outro, e aqui a mensagem chega em quem digitou o comando.
    owner = joblock.owner_pid(job_id)
    if owner is not None:
        print(
            f"O job {job_id} já está sendo processado pelo PID {owner}.\n"
            "Espere terminar ou encerre aquele processo antes de reanalisar.",
            file=sys.stderr,
        )
        raise SystemExit(1)

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    asyncio.run(_run(job_id))


if __name__ == "__main__":
    main()
