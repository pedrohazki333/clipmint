"""estilo: o rosa padrao vira o coral da marca (#FD375C -> #FF395E)

O app e os clipes passam a ter um rosa so. O padrao do estilo (`clip_style.py` e o
espelho `lib/clipStyle.ts`) ja mudou; isto leva junto os perfis que GRAVARAM o rosa
antigo -- seja por terem salvo o padrao, seja por terem escolhido o "rosa" da paleta,
que era o mesmo valor. Os dois casos querem dizer "o rosa da marca".

So o valor EXATO e trocado. Cor livre (o amarelo de uma pagina, um rosa parecido
escolhido a mao) nao e tocada. O contraste continua valendo: o coral fica a 5,6:1
sobre o fundo do titulo e da caixa, acima do minimo de 4,5:1.

`jobs.style_json` fica como esta de proposito: a copia do job e o registro do que
foi renderizado, e re-renderizar um job antigo deve dar o mesmo clipe.

O estilo e gravado em maiusculas (ver `_hex` em clip_style.py), entao a busca pelo
texto exato basta, e o REPLACE existe igual no SQLite e no Postgres.

Revision ID: 0017_coral_da_marca
Revises: 0016_estilo_do_clipe
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0017_coral_da_marca"
down_revision: Union[str, None] = "0016_estilo_do_clipe"
branch_labels: Union[Sequence[str], None] = None
depends_on: Union[Sequence[str], None] = None

ANTIGO = "#FD375C"
NOVO = "#FF395E"


def _troca(de: str, para: str) -> None:
    op.get_bind().execute(
        sa.text(
            "UPDATE profiles SET style_json = REPLACE(style_json, :de, :para) "
            "WHERE style_json LIKE :tem"
        ),
        {"de": de, "para": para, "tem": f"%{de}%"},
    )


def upgrade() -> None:
    _troca(ANTIGO, NOVO)


def downgrade() -> None:
    # Volta o coral para o rosa antigo. Não distingue quem escolheu o coral à mão
    # depois desta migração -- mas, antes dela, o coral não estava na paleta, e
    # voltar o sistema é voltar a paleta junto.
    _troca(NOVO, ANTIGO)
