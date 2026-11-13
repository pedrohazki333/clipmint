"""jobs: a capa enviada pela pessoa, no lugar da escolhida do clipe

So o layout "Capa + faixa" usa. Nulo = a capa e escolhida do clipe, como sempre.

Revision ID: 0018_capa_enviada
Revises: 0017_coral_da_marca
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0018_capa_enviada"
down_revision: Union[str, None] = "0017_coral_da_marca"
branch_labels: Union[Sequence[str], None] = None
depends_on: Union[Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("jobs") as batch:
        batch.add_column(sa.Column("cover_path", sa.Text(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("jobs") as batch:
        batch.drop_column("cover_path")
