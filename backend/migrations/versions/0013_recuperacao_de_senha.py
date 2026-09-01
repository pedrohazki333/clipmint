"""auth: o token que devolve a conta a quem esqueceu a senha

Sem isto, esquecer a senha e perder a conta eram a mesma coisa — e a conta tem
creditos comprados dentro. A unica saida era o dono editar o banco a mao, o que
nao escala para alem de uns poucos clientes.

Tabela propria, e nao uma coluna em `users`, por tres razoes:

1. um pedido de redefinicao e um EVENTO, nao um atributo da pessoa. Pedir duas
   vezes gera duas linhas, e a segunda nao apaga a primeira;
2. `used_at` guarda que aquele link ja foi gasto. Token de uso unico e o que
   impede que quem leia o e-mail depois (caixa compartilhada, encaminhamento)
   troque a senha de novo;
3. a limpeza dos expirados e um DELETE por data, sem tocar em `users`.

Guarda o HASH do token, nunca o token — mesma decisao de `sessions`, e pelo
mesmo motivo: um dump vazado nao pode virar acesso. SHA-256 basta, porque a
entropia vem do `secrets` e nao ha o que adivinhar.

Revision ID: 0013_recuperacao_de_senha
Revises: 0012_facecam_no_perfil
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0013_recuperacao_de_senha"
down_revision: Union[str, None] = "0012_facecam_no_perfil"
branch_labels: Union[Sequence[str], None] = None
depends_on: Union[Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "password_resets",
        sa.Column("token_hash", sa.String(), primary_key=True),
        sa.Column(
            "user_id",
            sa.String(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False, index=True),
        # NULO = ainda nao usado. Preenchido, o link esta gasto para sempre.
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_table("password_resets")
