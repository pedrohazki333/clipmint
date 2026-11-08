"""estilo: o visual do clipe por perfil, a copia no job e a palavra-chave do titulo

`profiles.style_json` guarda o estilo. Nulo em perfil antigo, e isso e de proposito:
ele e derivado dos JSONs de marca que o perfil ja tinha (ver app/clip_style.py), sem
gravar nada, e so vira linha aqui quando a pessoa salvar um.

`jobs.style_json` e a copia feita na criacao do job: mudar o perfil afeta os proximos
jobs, nunca reescreve o passado. Nulo em job antigo, que usa o do perfil.

`clips.hook_keyword` e a palavra do titulo que sai na cor da marca, escolhida pela
analise. Precisa ser guardada porque o re-render nao chama a analise de novo.

Revision ID: 0016_estilo_do_clipe
Revises: 0015_relato_de_enquadramento
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0016_estilo_do_clipe"
down_revision: Union[str, None] = "0015_relato_de_enquadramento"
branch_labels: Union[Sequence[str], None] = None
depends_on: Union[Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("profiles", sa.Column("style_json", sa.Text(), nullable=True))
    op.add_column("jobs", sa.Column("style_json", sa.Text(), nullable=True))
    op.add_column("clips", sa.Column("hook_keyword", sa.String(), nullable=True))


def downgrade() -> None:
    op.drop_column("clips", "hook_keyword")
    op.drop_column("jobs", "style_json")
    op.drop_column("profiles", "style_json")
