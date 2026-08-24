.PHONY: setup backend frontend dev backend-serve frontend-serve serve update-ytdlp emoji-font

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
