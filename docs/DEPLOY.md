# Deploy do ClipMint numa VPS

Guia do que a máquina precisa e do que configurar. A parte de banco tem um
documento próprio: `docs/POSTGRES.md`. As decisões por trás de cada escolha
estão em `docs/DECISOES.md`.

Escrito para **Ubuntu 24.04**. Onde outra versão muda o nome de um pacote, está
anotado.

---

## 1. A máquina

O gargalo não é a API — é o FFmpeg. Cada job renderiza vídeo e, no modo
streamer, roda MediaPipe quadro a quadro.

| | Recomendado | Por quê |
|---|---|---|
| vCPU | 4 | `MAX_CONCURRENT_JOBS=2` e o FFmpeg usa mais de um núcleo por job |
| RAM | 8 GB | MediaPipe + dois FFmpeg + Postgres |
| Disco | 80 GB+ | Um vídeo de origem em 4K passa de 1 GB; o TTL de download é de 3 dias |

Com 2 vCPU funciona, mas deixe `MAX_CONCURRENT_JOBS=1` — dois renders
disputando dois núcleos deixam **os dois** lentos.

**Disco é o recurso que para o sistema**, não o que o degrada: cheio, o FFmpeg
falha, o Postgres recusa escrita e tudo cai junto. A faxina automática (item 8)
existe por isso.

## 2. Pacotes de sistema

```bash
sudo apt update
sudo apt install -y \
  python3 python3-venv python3-dev \
  ffmpeg \
  postgresql postgresql-contrib \
  nginx certbot python3-certbot-nginx \
  git curl build-essential
```

E as bibliotecas que o MediaPipe e o OpenCV linkam — sem elas o `import cv2`
falha com "libGL.so.1: cannot open shared object file", que é um erro difícil de
associar à causa:

```bash
sudo apt install -y libgl1 libglib2.0-0t64 libsm6 libice6 libxext6 libgomp1
```

> No Ubuntu 22.04 o pacote é `libglib2.0-0` (sem o `t64`).

**Node 20+** (o do apt costuma estar velho demais):

```bash
curl -fsSL https://deb.nodesource.com/setup_20.x | sudo -E bash -
sudo apt install -y nodejs
```

Conferir tudo de uma vez:

```bash
python3 --version   # 3.11 ou mais novo
node --version      # 20 ou mais novo
ffmpeg -version     # 6.x testado
pg_isready          # accepting connections
```

## 3. Usuário e código

Rodar como usuário próprio, sem shell de login — se a aplicação for
comprometida, o atacante não ganha uma sessão.

```bash
sudo useradd --system --create-home --home-dir /opt/clipmint --shell /usr/sbin/nologin clipmint
sudo -u clipmint git clone https://github.com/SEU_USUARIO/clipmint.git /opt/clipmint/app
cd /opt/clipmint/app
sudo -u clipmint make setup
```

O `make setup` cria a venv, instala as dependências Python e roda o `npm install`.

**Depois do setup, atualize o yt-dlp para a nightly:**

```bash
sudo -u clipmint make update-ytdlp
```

Não é preciosismo. O YouTube muda a proteção de download periodicamente e a
versão estável do PyPI fica para trás — em 17/08/2026 ela parou de baixar
**qualquer** vídeo por dias. A correção sai antes na nightly.

## 4. Banco

Siga `docs/POSTGRES.md` (criar role e database) e volte aqui.

## 5. Variáveis de ambiente

```bash
sudo -u clipmint cp .env.example /opt/clipmint/app/.env
sudo -u clipmint nano /opt/clipmint/app/.env
sudo chmod 600 /opt/clipmint/app/.env
```

O arquivo tem 73 chaves possíveis, quase todas com padrão bom. **Cinco precisam
ser preenchidas** — sem elas o servidor não sobe ou não funciona:

| Variável | O que é |
|---|---|
| `PUBLIC_BUILD` | **`true`.** É o que tira Siege X e Melhorar vídeo do ar |
| `DATABASE_URL` | `postgresql+psycopg://clipmint:SENHA@localhost:5432/clipmint` |
| `CLIPMINT_PASSWORD` | Senha de perímetro da API. Gere com `openssl rand -base64 24` |
| `ASSEMBLYAI_API_KEY` | Transcrição |
| `ANTHROPIC_API_KEY` | Análise de viralidade |
| `OWNER_EMAIL` | **O seu e-mail.** É a conta que vai administrar — ver abaixo |

**Sobre o `OWNER_EMAIL`:** o cadastro público sempre cria conta comum, senão
qualquer um viraria administrador se cadastrando. A coroa é dada no startup à
conta que tiver esse e-mail — e o startup **não cria a conta**. A ordem é:
subir o servidor, cadastrar-se normalmente com esse e-mail, reiniciar. Deixando
o padrão `dono@clipmint.local`, ninguém administra o servidor, nem você, e o
painel `/admin` responde 403 para todo mundo.

Também deixe `SQLITE_URL=` **vazia**: ela é o nome antigo de `DATABASE_URL` e,
preenchida, vence — o servidor subiria em SQLite achando que está em Postgres.

**O servidor recusa subir** se `PUBLIC_BUILD=true` e faltar `CLIPMINT_PASSWORD`,
ou se o banco não for Postgres. Isso é de propósito: um servidor que não sobe é
um problema visível; um servidor aberto não é.

Vale revisar as travas de custo antes de abrir para alguém (os padrões públicos
já são conservadores):

```bash
PUBLIC_QUOTA_MAX_VIDEOS=10      # por usuário, por janela
PUBLIC_QUOTA_MAX_MINUTES=300    # o teto que segura a conta
PUBLIC_MAX_SOURCE_MINUTES=120   # por vídeo
MAX_CONCURRENT_JOBS=2
CLIP_TTL_DAYS=14
DOWNLOAD_TTL_DAYS=3
REGISTRATION_OPEN=true          # false abre só para quem já tem conta
```

### Pagamentos (Mercado Pago)

Sem estas duas o servidor **sobe normalmente**, mas a recarga responde 503 — dá
para colocar no ar e ligar o pagamento depois.

| Variável | Onde pegar |
|---|---|
| `MERCADOPAGO_ACCESS_TOKEN` | Suas integrações > credenciais. `TEST-` = sandbox, `APP_USR-` = produção |
| `MERCADOPAGO_WEBHOOK_SECRET` | Suas integrações > Webhooks > Configurar notificação |
| `PUBLIC_BASE_URL` | O endereço do site, ex. `https://clipmint.com.br`. Só a ASSINATURA depende dele |

O token é a ÚNICA coisa que decide contra qual ambiente as chamadas vão — não
existe flag de sandbox separada, de propósito: uma flag discordando do token
seria uma forma nova de cobrar de verdade achando que era teste.

No painel do Mercado Pago, cadastre a URL de notificação:

```
https://SEU_DOMINIO/api/billing/webhook
```

Essa rota passa pelas duas cercas de autenticação (o middleware do Next e a de
perímetro do backend) porque o gateway não tem sessão nem o token da instalação.
Quem autentica ali é a assinatura HMAC — e **sem `MERCADOPAGO_WEBHOOK_SECRET` o
endpoint recusa tudo**, em vez de aceitar tudo. Confira depois de subir:

```bash
# Sem assinatura válida tem que dar 401 vindo do BACKEND, não do middleware:
curl -s -X POST "https://SEU_DOMINIO/api/billing/webhook?data.id=X" \
  -H 'x-signature: ts=1,v1=deadbeef' -H 'x-request-id: r1' -d '{}'
# esperado: {"detail":"Assinatura inválida."}
# se vier {"detail":"Faça login para continuar"}, a rota está presa no Next
```

Nas notificações, marque também os assuntos de **assinatura**
(`subscription_preapproval` e `subscription_authorized_payment`) além de
`payment` — é o segundo que concede os créditos de cada mês.

**Antes do primeiro pagamento real**, faça uma compra no sandbox e confira o
status que o MP devolve contra a allowlist `_STATUS_PAGOS` de
`app/services/mercadopago.py` — a documentação não fecha a lista de estados
finais, e o que não está na lista não credita (ver D106).

### O YouTube bloqueia IP de datacenter

Num servidor, `yt-dlp` responde isto para **qualquer** vídeo, inclusive os
públicos há vinte anos:

```
ERROR: [youtube] ...: Sign in to confirm you're not a bot.
```

Não é o vídeo nem o link: é a faixa de IP. O mesmo endereço funciona numa
conexão doméstica e falha na VPS. Confirme com um vídeo de controle antes de
culpar o seu link:

```bash
cd /opt/clipmint/app/backend
sudo -u clipmint .venv/bin/python -m yt_dlp --skip-download \
  --print "%(duration)s" "https://www.youtube.com/watch?v=jNQXAC9IVRw"
```

Falhando também nesse, é o IP. A saída é preencher `YTDLP_COOKIES_FILE` (ou
`YTDLP_PROXY`) no `.env` — as duas valem para a consulta de metadados **e** para
o download, que compartilham as opções (`app/utils/ytdlp.py`).

Para os cookies: exporte de um navegador logado numa **conta descartável**, no
formato Netscape, e ponha o arquivo em algo como
`/opt/clipmint/app/backend/storage/cookies.txt`, com dono `clipmint` e
`chmod 600` — é uma credencial de sessão do Google.

#### Um runtime de JavaScript é obrigatório

Só cookies não bastam. O YouTube exige resolver um desafio em JavaScript, e sem
um runtime instalado o `yt-dlp` responde **"The page needs to be reloaded"** —
mensagem que não sugere em nada a causa real. O diagnóstico está no `-v`:

```
[debug] JS runtimes: none
[debug] [youtube] [jsc] JS Challenge Providers: deno (unavailable), node (unavailable), ...
```

O Node do sistema **não serve** (o yt-dlp o reporta como indisponível mesmo
instalado e no PATH). Instale o Deno:

```bash
sudo apt install -y unzip
curl -fsSL -o /tmp/deno.zip https://github.com/denoland/deno/releases/latest/download/deno-x86_64-unknown-linux-gnu.zip
sudo unzip -o /tmp/deno.zip -d /usr/local/bin && sudo chmod 755 /usr/local/bin/deno && rm /tmp/deno.zip
```

Confirme com o vídeo de controle: `JS runtimes: deno-...` e a duração impressa.

#### O arquivo de cookies é protegido pelo app

O `yt-dlp` **reescreve** o arquivo que recebe em `cookiefile`. Quando a sessão é
rejeitada, ele salva por cima um jar sem os cookies de autenticação — em
produção, 27/08/2026, o arquivo caiu de 2954 para 1843 bytes e perdeu `SID`,
`HSID`, `SSID`, `APISID`, `SAPISID`, `LOGIN_INFO` e `__Secure-1PSID` numa única
tentativa. Depois disso o erro volta a ser "confirme que você não é um robô",
apontando para o lugar errado.

Por isso `app/utils/ytdlp.py` entrega uma **cópia descartável** a cada chamada e
nunca o arquivo original. Ao reexportar, exporte de uma **janela anônima** e
feche-a sem fazer logout: sessão anônima não continua sendo usada pelo
navegador, então não rotaciona por baixo dos panos.

Sem nenhuma das duas, o guarda de custo recusa o job **antes** de gastar
qualquer coisa, com a mensagem "não foi possível descobrir a duração deste
vídeo". Falhar fechado ali é de propósito (ver D45): a alternativa deixou um
link de live baixar 18 GB.

## 6. Build

```bash
cd /opt/clipmint/app
sudo -u clipmint make build-public
```

> ### Duas coisas ficam CONGELADAS no build do frontend
>
> 1. **`BACKEND_PORT`** — o proxy `/api/*` é resolvido em tempo de build e
>    gravado no `routes-manifest.json`. Mudar a porta depois e só reiniciar
>    **não tem efeito**: o proxy continua apontando para a antiga.
> 2. **`CLIPMINT_PASSWORD`** — no build pessoal ela é embutida no bundle do
>    servidor. (No build público não: ela não é injetada, verificado.)
>
> **Mudou qualquer uma das duas? Refaça o build.** As duas foram descobertas
> testando, não lendo a documentação do Next.

A saída vai para `frontend/.next-public`, não `.next` — assim um build público
nunca sobrescreve o `.next` de um `next dev` que esteja rodando.

## 7. Serviços

Dois serviços: a API e o servidor do Next.

**`/etc/systemd/system/clipmint-api.service`**

```ini
[Unit]
Description=ClipMint API
After=network.target postgresql.service
Requires=postgresql.service

[Service]
Type=exec
User=clipmint
WorkingDirectory=/opt/clipmint/app/backend
# 127.0.0.1: quem vem de fora entra pelo frontend, que faz o proxy por
# localhost. Uma porta exposta em vez de duas.
ExecStart=/opt/clipmint/app/backend/.venv/bin/uvicorn app.main:app \
    --host 127.0.0.1 --port 8001 --proxy-headers
Restart=always
RestartSec=5
# O pipeline roda dentro deste processo: um render de vídeo pode levar minutos,
# e o systemd não pode confundir isso com travamento.
TimeoutStopSec=300

[Install]
WantedBy=multi-user.target
```

**`/etc/systemd/system/clipmint-web.service`**

```ini
[Unit]
Description=ClipMint (frontend)
After=network.target clipmint-api.service

[Service]
Type=exec
User=clipmint
WorkingDirectory=/opt/clipmint/app/frontend
Environment=NODE_ENV=production
Environment=PUBLIC_BUILD=true
Environment=PORT=3000
ExecStart=/usr/bin/npm run start
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now clipmint-api clipmint-web
sudo systemctl status clipmint-api clipmint-web
journalctl -u clipmint-api -f     # o log do pipeline sai aqui
```

**Reiniciar a API mata os jobs em andamento.** Eles voltam como erro e o botão
"Retomar" reaproveita download, transcrição e análise já feitos — nada é pago
duas vezes. Ainda assim, prefira reiniciar quando não houver job rodando.

## 8. Nginx e HTTPS

```nginx
server {
    server_name clipmint.seudominio.com;

    # Upload de clipe de referência vai até 500 MB.
    client_max_body_size 512M;

    location / {
        proxy_pass http://127.0.0.1:3000;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        # Render de vídeo e transcrição demoram: o padrão de 60s cortaria a
        # resposta no meio.
        proxy_read_timeout 600s;
    }
}
```

```bash
sudo ln -s /etc/nginx/sites-available/clipmint /etc/nginx/sites-enabled/
sudo nginx -t && sudo systemctl reload nginx
sudo certbot --nginx -d clipmint.seudominio.com
```

**Com HTTPS no ar, marque o cookie como `secure`.** Ele hoje não é marcado
porque o acesso pessoal pode ser HTTP puro numa rede privada (Tailscale), e ali
o cookie nem seria gravado — ver `_set_session_cookie` em
`backend/app/routers/auth.py`.

O firewall só precisa de duas portas:

```bash
sudo ufw allow OpenSSH && sudo ufw allow 'Nginx Full' && sudo ufw enable
```

## 9. Conferir que subiu certo

> **A ordem importa.** Sem sessão, o middleware barra tudo **antes** de a rota
> ser resolvida: `/siege` responde `307` (redireciona para o login), não `404`.
> Para conferir que a rota realmente não existe é preciso estar autenticado —
> daí o passo 3 vir antes do 4. Rodar na ordem errada faz parecer que o build
> saiu errado.

```bash
API=localhost:8001
WEB=localhost:3000

# 1. A API responde
curl -s $API/health                                     # {"status":"ok"}

# 2. Sem sessão, nada é acessível
curl -s -o /dev/null -w "%{http_code}\n" $WEB/api/jobs  # 401
curl -s -o /dev/null -w "%{http_code}\n" $WEB/          # 307 → /login

# 3. Criar uma conta de teste e guardar o cookie
curl -s -o /dev/null -c /tmp/cm.txt -X POST $WEB/api/auth/register \
  -H 'Content-Type: application/json' \
  -d '{"email":"teste@exemplo.com","password":"uma-senha-bem-longa"}'

# 4. AGORA sim: as features pessoais não existem
for r in /siege /melhorar-video /api/video-enhance; do
  echo -n "$r → "; curl -s -o /dev/null -w "%{http_code}\n" -b /tmp/cm.txt $WEB$r
done                                                    # 404, 404, 404

# 5. O nicho pessoal é recusado; as contas públicas funcionam
curl -s -o /dev/null -w "%{http_code}\n" -b /tmp/cm.txt "$WEB/api/jobs?source=siege"  # 422
curl -s -o /dev/null -w "%{http_code}\n" -b /tmp/cm.txt "$WEB/podcast"                # 200

# 6. A porta do build pessoal não existe aqui
curl -s -o /dev/null -w "%{http_code}\n" -X POST $WEB/auth/login   # 404

# 7. O banco está na última revisão
cd /opt/clipmint/app && sudo -u clipmint make db-current   # deve dizer (head)

# 8. Nada de pessoal no bundle que o navegador baixa
grep -ril "siege\|video-enhance" frontend/.next-public/static | wc -l   # 0
```

Apague a conta de teste depois (`DELETE FROM users WHERE email='teste@exemplo.com'`).

Por fim, pelo navegador: crie uma conta, mande um vídeo curto, e confira que o
clipe sai e baixa.

## 10. Manutenção

| Tarefa | Como | Quando |
|---|---|---|
| Atualizar yt-dlp | `make update-ytdlp` + `systemctl restart clipmint-api` | Ao primeiro download que falhar com 403 |
| Backup do banco | `pg_dump -U clipmint clipmint \| gzip > …` | Diário, no cron |
| Faxina do storage | Automática a cada 6 h | — |
| Ver o que a faxina apagaria | `make cleanup-dry` | Quando o disco preocupar |
| Espaço em disco | `df -h /` | Monitorar |

A faxina roda dentro do servidor (`CLEANUP_INTERVAL_HOURS=6`). Para tirá-la de
lá e pôr no cron, use `CLEANUP_INTERVAL_HOURS=0` e:

```cron
0 4 * * * cd /opt/clipmint/app/backend && .venv/bin/python -m app.scripts.cleanup
0 3 * * * pg_dump -U clipmint clipmint | gzip > /opt/backups/clipmint-$(date +\%F).sql.gz
```

**A fonte de emoji não vai no git** (são 10 MB de binário). Sem ela, o emoji do
gancho some do banner — o clipe sai certo, só sem ele:

```bash
sudo -u clipmint make emoji-font
```

## 11. Atualizar o código

```bash
cd /opt/clipmint/app
sudo -u clipmint git pull
sudo -u clipmint backend/.venv/bin/pip install -r backend/requirements.txt
sudo -u clipmint make build-public          # refaça sempre: ver o aviso do item 6
sudo systemctl restart clipmint-api clipmint-web
```

As migrações do banco são aplicadas sozinhas no startup da API.

---

## O que este deploy ainda NÃO resolve

Honestidade sobre os limites do que foi entregue:

- **Sem pagamento.** Ficou fora desta passada por decisão sua.
- **Um servidor só.** O pipeline roda dentro do processo da API e usa um lock
  por arquivo; escalar para duas máquinas exige fila de verdade (Celery/Redis) e
  storage compartilhado.
- **Sem e-mail.** Não há recuperação de senha nem confirmação de cadastro.
- **Sem monitoramento.** `journalctl` é o que existe.
