"""facecam: o relato de enquadramento errado, e o que ele libera

A caixa da facecam e detectada por heuristica, e heuristica erra. Quando erra, o
painel de cima sai com gameplay dentro e a cabeca do streamer cortada — o
cliente pagou e recebeu um clipe que nao presta.

Corrigir a mao exige servir quadros do video de origem e re-renderizar, e as
duas coisas custam CPU. Liberar isso para qualquer um clicar transformaria um
botao em vetor de desperdicio: bastaria pedir correcao em todo job.

Entao existe uma porta: o cliente sobe um PRINT do enquadramento ruim e
descreve o problema; a visao olha o print e diz se esta ruim de fato. So um
relato aprovado destranca o corretor.

Aponta para o CLIP, nao so para o job: e o clipe que ficou torto, e e o
intervalo dele que a linha do tempo do corretor precisa varrer. Um job de 8
clipes pode ter um so errado.

`veredito` guarda o que a visao respondeu, em texto. Ele nao e so registro: e o
que a tela mostra a quem teve o relato recusado, e sem ele "recusado" seria uma
parede sem explicacao.

Revision ID: 0015_relato_de_enquadramento
Revises: 0014_facecam_so_por_video
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0015_relato_de_enquadramento"
down_revision: Union[str, None] = "0014_facecam_so_por_video"
branch_labels: Union[Sequence[str], None] = None
depends_on: Union[Sequence[str], None] = None

_STATUS = "status IN ('analisando', 'aprovado', 'recusado')"


def upgrade() -> None:
    op.create_table(
        "facecam_reports",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column(
            "job_id",
            sa.String(),
            sa.ForeignKey("jobs.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        # O clipe que saiu torto. NULO se ele apagou o clipe depois de relatar —
        # o relato continua valendo para o job.
        sa.Column("clip_id", sa.String(), nullable=True),
        sa.Column("user_id", sa.String(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("screenshot_path", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False, server_default="analisando"),
        sa.Column("veredito", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(_STATUS, name="ck_facecam_reports_status"),
    )


def downgrade() -> None:
    op.drop_table("facecam_reports")
