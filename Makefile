.PHONY: setup backend frontend dev backend-serve frontend-serve serve

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
