# Postgres — o que configurar no servidor

Guia da parte de banco do deploy. O resto (FFmpeg, serviços, variáveis) fica em
`docs/DEPLOY.md`, escrito na fatia de deploy.

O ClipMint fala dois dialetos de propósito: **SQLite** na versão pessoal e nos
testes, **Postgres** no build público. O build público *recusa subir* em SQLite
— um servidor multiusuário escrevendo num arquivo só corrompe sob concorrência,
e é melhor descobrir isso no startup do que na primeira escrita simultânea.

---

## 1. Instalar

```bash
sudo apt update
sudo apt install -y postgresql postgresql-contrib
sudo systemctl enable --now postgresql
pg_isready            # deve responder "accepting connections"
```

Qualquer versão a partir da 14 serve. Testado na **16**.

## 2. Criar o usuário e o banco

```bash
sudo -u postgres psql \
  -c "CREATE ROLE clipmint LOGIN PASSWORD 'TROQUE_ESTA_SENHA';" \
  -c "CREATE DATABASE clipmint OWNER clipmint;"
```

O `OWNER clipmint` importa: é o que permite ao Alembic criar e alterar tabelas
sem precisar de superusuário. Rodar migração como `postgres` funcionaria, mas
deixaria a aplicação com poder que ela não precisa ter o tempo todo.

Conferir:

```bash
PGPASSWORD='TROQUE_ESTA_SENHA' psql -h localhost -U clipmint -d clipmint \
  -c "SELECT current_database(), current_user;"
```

## 3. Apontar a aplicação

No `.env` da raiz:

```bash
DATABASE_URL=postgresql+psycopg://clipmint:TROQUE_ESTA_SENHA@localhost:5432/clipmint
```

O driver é o **psycopg** (psycopg 3), não o `psycopg2` nem o `asyncpg`: ele fala
síncrono e assíncrono, então serve à aplicação (async) e ao Alembic (sync) sem
dois drivers para manter.

**Atenção ao nome antigo:** se o `.env` ainda tiver `SQLITE_URL` preenchido, é
ele que vence — de propósito, para um `.env` que já funcionava não trocar de
banco porque uma variável nova apareceu. No servidor, apague a linha
`SQLITE_URL`; definir `DATABASE_URL` sozinho não basta.

### Rodando o build público na SUA máquina, ao lado da versão pessoal

`make serve-public` sobe a versão pública em 3001/8002 para conferir antes de
publicar, convivendo com o `make dev`. Aí o `DATABASE_URL` **não** serve: o
`.env` é um só para as duas versões, e apontá-lo para o Postgres levaria junto a
versão pessoal, que tem o histórico de jobs no `clipmint.db`. Use a variável
própria:

```bash
PUBLIC_DATABASE_URL=postgresql+psycopg://clipmint:SENHA@localhost:5432/clipmint
```

O Makefile passa essa URL só para o processo público (e zera o `SQLITE_URL` dele,
senão o nome antigo ganharia). No servidor, onde só existe o build público, ela
fica vazia e vale o `DATABASE_URL` de cima.

Se a senha tiver caractere especial (`@`, `:`, `/`), ela precisa ir
percent-encoded na URL, senão o endereço é lido errado:

```python
from urllib.parse import quote_plus
quote_plus("minha@senha")   # 'minha%40senha'
```

## 4. Aplicar as migrações

O servidor faz isso sozinho no startup. Para rodar à mão (ou conferir antes):

```bash
cd backend
.venv/bin/alembic upgrade head      # aplica
.venv/bin/alembic current           # em que revisão está
.venv/bin/alembic history           # o caminho todo
```

A URL **não** está no `alembic.ini`: vem do `.env` da raiz, via
`migrations/env.py`. Uma segunda cópia acabaria aplicando migração no banco
errado.

## 5. Levar os dados que já existem

Só é preciso se você quiser o histórico do SQLite no servidor.

```bash
cd backend

# 1. confere o que seria copiado, sem escrever nada
.venv/bin/python -m app.scripts.migrate_to_postgres --dry-run \
  --destino "postgresql+psycopg://clipmint:SENHA@localhost:5432/clipmint"

# 2. copia
.venv/bin/python -m app.scripts.migrate_to_postgres \
  --destino "postgresql+psycopg://clipmint:SENHA@localhost:5432/clipmint"
```

O script **nunca modifica a origem** — se algo der errado no meio, o SQLite
continua sendo a cópia boa. E ele recusa escrever num destino que já tenha
linhas, porque copiar por cima duplicaria dado e quebraria na chave primária no
meio do caminho.

Os **arquivos** (vídeos, clips, transcrições em `storage/`) não vão pelo script:
são grandes e não são banco. Copie com `rsync`:

```bash
rsync -av --progress backend/storage/ usuario@servidor:/opt/clipmint/backend/storage/
```

---

## Backup

Um comando, e vale a pena estar no cron **antes** do primeiro usuário real:

```bash
pg_dump -U clipmint -h localhost clipmint | gzip > clipmint-$(date +%F).sql.gz
```

Restaurar:

```bash
gunzip -c clipmint-2026-08-25.sql.gz | psql -U clipmint -h localhost clipmint
```

O banco guarda o texto e as decisões (jobs, notas, exemplos validados,
métricas); os arquivos de vídeo ficam em `storage/` e têm o próprio ciclo de
vida — a partir da Fatia 7, com TTL. Backup do banco é barato e é o que não dá
para refazer; backup dos vídeos é caro e refazível.

---

## Se der errado

| Sintoma | Causa provável |
|---|---|
| `password authentication failed` | Senha errada, ou não percent-encoded na URL |
| `role "clipmint" does not exist` | O passo 2 não rodou |
| `permission denied for schema public` | O banco foi criado sem `OWNER clipmint` |
| `Can't load plugin: sqlalchemy.dialects:postgresql.psycopg` | Falta `pip install -r requirements.txt` (o psycopg entrou na Fatia 5) |
| Startup morre com "o build PÚBLICO exige PostgreSQL" | `DATABASE_URL` ainda aponta para SQLite |
| `connection ... server closed the connection unexpectedly` | Conexão morta em fila de proxy; o `pool_pre_ping` já cobre — se persistir, é rede |

## Ajuste fino (só se precisar)

O pool vem de `DB_POOL_SIZE` (10) e `DB_MAX_OVERFLOW` (5) no `.env`. Dez
conexões cobrem com folga a concorrência de jobs que o servidor vai permitir —
não aumente sem antes olhar `max_connections` do Postgres (padrão: 100) e o
limite de jobs simultâneos da Fatia 7.
