"""
Retoma um job fora do servidor web.

    cd backend && .venv/bin/python -m app.scripts.resume_job <job_id>

Mesma lógica do endpoint POST /api/jobs/<id>/retry, mas num processo próprio:
o render não morre quando o uvicorn recarrega (o `--reload` do `make dev`
reinicia o servidor a cada arquivo salvo, matando os jobs em andamento).
Útil para jobs longos — vídeos de horas, muitos clips em 4K.

O progresso aparece normalmente na UI: o script escreve no mesmo banco.
"""

import asyncio
import logging
import sys

from app.workers.pipeline import run_pipeline


def main() -> None:
    if len(sys.argv) != 2:
        print(__doc__.strip(), file=sys.stderr)
        raise SystemExit(2)

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    asyncio.run(run_pipeline(sys.argv[1], resume=True))


if __name__ == "__main__":
    main()
