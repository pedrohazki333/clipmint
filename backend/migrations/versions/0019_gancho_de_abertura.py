"""gancho de abertura: a fala mais forte do clipe antes do comeco dele

- jobs.opening_hook: o job pediu o gancho (escolha da tela de gerar).
- clips.opening_json: onde a fala foi dita, [inicio, fim, "texto"].

Revision ID: 0019_gancho_de_abertura
Revises: 0018_capa_enviada
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0019_gancho_de_abertura"
down_revision: Union[str, None] = "0018_capa_enviada"
branch_labels: Union[Sequence[str], None] = None
depends_on: Union[Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("jobs") as batch:
        batch.add_column(
            sa.Column("opening_hook", sa.Boolean(), nullable=False, server_default=sa.false())
        )
    with op.batch_alter_table("clips") as batch:
        batch.add_column(sa.Column("opening_json", sa.Text(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("clips") as batch:
        batch.drop_column("opening_json")
    with op.batch_alter_table("jobs") as batch:
        batch.drop_column("opening_hook")
