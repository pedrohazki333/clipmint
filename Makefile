.PHONY: setup backend frontend dev backend-serve frontend-serve serve \
        build-public serve-public _serve-public-backend _serve-public-frontend \
        compare-transcribers db-upgrade db-current db-history db-revision \
        db-upgrade-public db-current-public \
        cleanup cleanup-dry \
        update-ytdlp emoji-font

# Porta do backend lida do .env da raiz — o mesmo arquivo que o next.config lê
# para montar o proxy. Uma fonte só: o uvicorn e o proxy não têm como divergir.
BACKEND_PORT := $(shell sed -n 's/^BACKEND_PORT=[^0-9]*\([0-9][0-9]*\).*/\1/p' .env 2>/dev/null | tail -1)
BACKEND_PORT := $(if $(BACKEND_PORT),$(BACKEND_PORT),8001)

setup:
	cd backend && python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
	cd frontend && npm install

backend:
	cd backend && .venv/bin/uvicorn app.main:app --reload --host 0.0.0.0 --port $(BACKEND_PORT)

frontend:
	cd frontend && npm run dev

dev:
	@echo "Starting backend and frontend..."
	@make -j2 backend frontend

# ── Modo desatendido (acesso remoto) ──────────────────────────────────────────
# Sem --reload: salvar um .py reinicia o uvicorn e mata o job em andamento, o
# que é exatamente o que não pode acontecer com você longe da máquina.
# O backend fica só em 127.0.0.1 — quem vem de fora entra pelo frontend, que
# faz o proxy por localhost. Uma porta exposta em vez de duas.
backend-serve:
	cd backend && .venv/bin/uvicorn app.main:app --host 127.0.0.1 --port $(BACKEND_PORT)

frontend-serve:
	cd frontend && npm run build && npm run start

serve:
	@echo "Modo desatendido (sem reload). Ctrl+C para parar."
	@make -j2 backend-serve frontend-serve

# ── Build público ─────────────────────────────────────────────────────────────
# O produto que vai para o ar: sem o nicho Siege X e sem a aba Melhorar vídeo.
# É o MESMO código — o que muda é a flag PUBLIC_BUILD (ver backend/app/features.py
# e frontend/next.config.ts). No frontend as rotas dessas features nem chegam a
# ser compiladas; no backend os endpoints não são registrados.
#
# A saída vai para frontend/.next-public, e não para .next: um build público por
# cima do .next quebra o `next dev` da versão pessoal que estiver rodando.
# A porta do backend público. Deslocada da pessoal para os dois conviverem, e
# declarada UMA vez: o build assa esta porta dentro do rewrite e o uvicorn tem
# que escutar exatamente nela.
PUBLIC_BACKEND_PORT := 8002

# Storage próprio do build público. Sem isto ele divide o ./storage com a versão
# pessoal e passa a ler os presets de MARCA do dono — a demo aparecia com a logo
# dele (ver D100, que já previa isto; só o Makefile tinha ficado de fora, embora
# o .gitignore já esperasse a pasta).
PUBLIC_STORAGE_DIR := ./storage-demo

# O banco do build público. Mora numa variável PRÓPRIA (PUBLIC_DATABASE_URL) e
# não em DATABASE_URL porque o .env é UM SÓ para as duas versões: um Postgres em
# DATABASE_URL levaria junto o `make dev` pessoal, que tem todo o histórico de
# jobs no clipmint.db. Mesma lógica das portas deslocadas logo acima — as duas
# versões têm que conviver na mesma máquina.
#
# Lida DENTRO da receita, e não com $(shell), para o make não tentar expandir um
# `$` que exista na senha. O resultado de $(...) no shell não sofre nova
# expansão, então senha com caractere especial passa inteira.
PUBLIC_DB_URL = sed -n 's/^PUBLIC_DATABASE_URL=//p' ../.env | tail -1

# O BACKEND_PORT aqui não é decoração: `rewrites()` do next.config é avaliado no
# BUILD e serializado em .next-public/routes-manifest.json — `next start` não o
# recalcula. Sem passar a porta aqui, o build assa a BACKEND_PORT do .env (a do
# backend PESSOAL) e todo /api/* do site público vai bater numa porta que, no
# servidor de verdade, não tem ninguém: ECONNREFUSED, 500 em cima do login.
build-public:
	cd frontend && PUBLIC_BUILD=true BACKEND_PORT=$(PUBLIC_BACKEND_PORT) npm run build

# Sobe a versão pública para conferir antes de publicar. Portas deslocadas
# (3001/8002) para conviver com o `make dev` da versão pessoal.
serve-public: build-public
	@echo "Versão PÚBLICA em http://localhost:3001 (backend em $(PUBLIC_BACKEND_PORT))"
	@make -j2 _serve-public-backend _serve-public-frontend

# O --no-proxy-headers não é detalhe. O uvicorn liga proxy-headers por padrão e,
# confiando no peer loopback, troca request.client.host pelo X-Forwarded-For que
# o proxy do Next injeta — o IP do NAVEGADOR. A cerca de perímetro de main.py
# passa a ver o proxy como externo e exige o x-clipmint-token, que o build
# público não tem para dar (next.config zera CLIPMINT_PASSWORD ali de propósito).
# Resultado sem a flag: 401 "Não autorizado" em tudo que não seja login, para
# quem não entra por localhost. Aqui não se perde nada: o backend está preso em
# 127.0.0.1, então o único peer possível já é um processo desta máquina.
#
# O SQLITE_URL= vazio não é sobra: o nome antigo da variável VENCE o novo (ver
# config.db_url), então sem zerá-lo aqui o SQLITE_URL que o .env tem para a
# versão pessoal ganharia do Postgres e o guard de startup recusaria subir.
_serve-public-backend:
	@cd backend && test -n "$$($(PUBLIC_DB_URL))" || { \
		echo "PUBLIC_DATABASE_URL não está no .env da raiz."; \
		echo "Ex.: PUBLIC_DATABASE_URL=postgresql+psycopg://clipmint:SENHA@localhost:5432/clipmint"; \
		echo "Ver docs/POSTGRES.md."; exit 1; }
	cd backend && PUBLIC_BUILD=true SQLITE_URL= DATABASE_URL="$$($(PUBLIC_DB_URL))" STORAGE_DIR=$(PUBLIC_STORAGE_DIR) .venv/bin/uvicorn app.main:app --host 127.0.0.1 --port $(PUBLIC_BACKEND_PORT) --no-proxy-headers

_serve-public-frontend:
	cd frontend && PUBLIC_BUILD=true PORT=3001 BACKEND_PORT=$(PUBLIC_BACKEND_PORT) npm run start

# ── Faxina do storage ─────────────────────────────────────────────────────────
# O servidor roda isto sozinho (CLEANUP_INTERVAL_HOURS). Estes alvos são para
# rodar à mão. O --dry-run mostra o que sairia sem apagar nada.
cleanup-dry:
	@cd backend && .venv/bin/python -m app.scripts.cleanup --dry-run

cleanup:
	cd backend && .venv/bin/python -m app.scripts.cleanup

# ── Banco ─────────────────────────────────────────────────────────────────────
# O servidor aplica as migrações sozinho no startup; estes alvos são para
# inspecionar e para rodar à mão antes de subir. A URL vem do .env da raiz.
db-upgrade:
	cd backend && .venv/bin/alembic upgrade head

# O mesmo, no banco do build PÚBLICO. Alvo separado porque a URL vem de outra
# variável e o SQLITE_URL precisa ser zerado (o nome antigo vence o novo) — os
# mesmos dois cuidados do _serve-public-backend, num lugar só.
# O servidor aplica as migrações sozinho no startup; isto é para rodar antes,
# à mão, e para inspecionar.
db-upgrade-public:
	@cd backend && test -n "$$($(PUBLIC_DB_URL))" || { \
		echo "PUBLIC_DATABASE_URL não está no .env da raiz. Ver docs/POSTGRES.md."; \
		exit 1; }
	cd backend && SQLITE_URL= DATABASE_URL="$$($(PUBLIC_DB_URL))" .venv/bin/alembic upgrade head

db-current-public:
	@cd backend && SQLITE_URL= DATABASE_URL="$$($(PUBLIC_DB_URL))" .venv/bin/alembic current

db-current:
	@cd backend && .venv/bin/alembic current

db-history:
	@cd backend && .venv/bin/alembic history

# Cria uma migração nova a partir da diferença entre models.py e o banco.
# SEMPRE revise o arquivo gerado antes de aplicar: o autogenerate não entende
# renomeação (vê um DROP e um ADD) nem dado que precise ser preservado.
#   make db-revision M="descricao curta"
db-revision:
	cd backend && .venv/bin/alembic revision --autogenerate -m "$(M)"

# ── Avaliação de provedor de transcrição ──────────────────────────────────────
# Roda o MESMO áudio pelo AssemblyAI e pelo Deepgram e mostra texto, tempo e
# custo lado a lado. Cada provedor é cobrado por execução — é o preço de decidir
# com dado em vez de impressão.
#   make compare-transcribers JOB=<job_id>
#   make compare-transcribers AUDIO=/caminho/audio.wav
compare-transcribers:
	@cd backend && .venv/bin/python -m app.scripts.compare_transcribers \
		$(if $(JOB),$(JOB),) $(if $(AUDIO),--audio $(AUDIO),) $(if $(PROVIDERS),--providers $(PROVIDERS),)

# ── Manutenção ────────────────────────────────────────────────────────────────
# O YouTube muda a proteção de download de tempos em tempos e a versão estável
# do yt-dlp no PyPI fica para trás — em 17/08/2026 ela parou de baixar QUALQUER
# vídeo por dias. A correção sai antes na nightly, então é ela que o projeto
# usa. Rodar quando um download falhar com 403 (é a primeira coisa a tentar).
update-ytdlp:
	cd backend && .venv/bin/pip install --upgrade --pre "yt-dlp[default]"
	@cd backend && .venv/bin/python -c "import yt_dlp; print('yt-dlp agora:', yt_dlp.version.__version__)"

# A NotoColorEmoji é o que faz o emoji do hook aparecer colorido no banner dos
# clips (ver services/layout.py). Sem ela o emoji é removido do título — o clip
# sai certo, só sem ele. Não vai no git: são 10MB de binário.
emoji-font:
	@mkdir -p backend/storage/branding/fonts
	@curl -fsSL -o backend/storage/branding/fonts/NotoColorEmoji.ttf \
		https://raw.githubusercontent.com/googlefonts/noto-emoji/main/fonts/NotoColorEmoji.ttf
	@cd backend && .venv/bin/python -c "from app.services.layout import emoji_font_path; print('fonte de emoji:', emoji_font_path() or 'NAO ENCONTRADA')"
