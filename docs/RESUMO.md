# O que mudou, e o que falta

Resumo das oito fatias que prepararam o ClipMint para virar produto público.
O detalhe de cada decisão — e o porquê — está em `docs/DECISOES.md` (61
decisões numeradas).

**Números:** 378 → **548 testes**, 56 arquivos alterados, 32 criados,
4 migrações de banco.

---

## As oito fatias

### 1 · Separação público × pessoal

Um único codebase, duas versões, controladas por `PUBLIC_BUILD` no `.env`.
Siege X e Melhorar vídeo continuam inteiras na versão pessoal e **não existem**
no público — nem como rota, nem como código no bundle.

Duas camadas: as páginas pessoais se chamam `page.personal.tsx` e o Next só as
reconhece como rota quando `pageExtensions` as inclui; e o que a home precisa
saber sobre elas é trocado por um stub vazio via `NormalModuleReplacementPlugin`.

Guardado por 31 testes que sobem a API com a flag ligada e afirmam 404 em cada
endpoint. Critério de aceite verificável:

```bash
make build-public
grep -ril "siege\|video-enhance" frontend/.next-public/static  # vazio
```

### 2 · Auditoria

17 achados: 3 quebravam o fluxo principal, 8 eram risco de custo ou erro
silencioso, 6 eram diagnóstico. Relatório entregue antes de qualquer correção,
com a divisão do que corrigir agora, adiar ou não corrigir.

### 3 · Correções

| | |
|---|---|
| FFmpeg travado | Teto de tempo, matando o **grupo** de processos |
| URL de Shorts/live | Recusada pelo front que o back aceitava — regex unificado, com teste de paridade |
| `DELETE` em job rodando | Não parava o pipeline; deixava linhas e GB órfãos |
| Erros na tela | `app/errors.py` traduz 20 falhas conhecidas em frases que dizem o que fazer |
| "0 clipes" | Diz o motivo real, em vez de afirmar sempre o mesmo |
| Upload | Lido em pedaços; o teto de 500 MB passou a valer **durante** a leitura |
| Senha vazia | O build público recusa subir |
| Polling | Para em 404; erro de rede continua tentando |

### 4 · Transcrição plugável

`services/transcription/`: um contrato, um arquivo por provedor, um registro.
AssemblyAI segue o padrão; Deepgram Nova-3 entrou como alternativa. O pipeline
não mudou uma linha.

O **modo de comparação** (`make compare-transcribers`) roda o mesmo áudio pelos
dois e mede o que decide a troca *neste* projeto: fração de palavras abaixo de
0,7 de confiança, maior sequência repetida, palavras sem duração própria — os
três defeitos que já apareceram em material real.

**Dado que muda a leitura:** pela tabela de 25/08/2026, o Deepgram
(US$ 0,258/h) é **~23% mais caro** que o AssemblyAI (US$ 0,21/h). A troca não é
economia.

### 5 · Postgres e Alembic

O `ALTER TABLE` manual saiu — ele só falava SQLite e emitia um tipo que **não
existe no Postgres**. Agora são migrações de verdade, aplicadas no startup, com
carimbo automático de bancos anteriores ao Alembic.

Os dois dialetos convivem de propósito: SQLite na versão pessoal e nos testes,
Postgres no público (que recusa subir em SQLite).

Testar contra um Postgres real achou **duas falhas que os testes não pegavam** —
as transcrições órfãs bloqueando a migração por chave estrangeira, e
`https://youtu.be/` passando por toda a validação.

### 6 · Contas e isolamento

Cadastro, login e sessão no build público; a versão pessoal segue com a senha
única e um usuário-dono semeado, então o resto do sistema fala em "usuário" nas
duas.

Sessão no banco (revogável, ao contrário de JWT), token guardado como hash,
Argon2id nas senhas. Recurso de outra pessoa responde **404, nunca 403** — um
403 confirmaria que o id existe.

24 testes de isolamento, mais verificação ao vivo através do proxy real.

### 7 · Travas de custo e retenção

Cota por usuário (vídeos **e** minutos, janela deslizante), teto de duração
conferido antes do download, live recusada, duplicata barrada, concorrência
limitada, e TTL que apaga o **arquivo** do clipe mas nunca a linha — nota e
desempenho real alimentam o few-shot.

Padrões diferentes por build: na versão pessoal cota e teto vêm desligados.

### 8 · Refino visual

Tokens num arquivo só (eram 14 cinzas em ~380 usos, 5 raios, nenhuma fonte).
IBM Plex Sans + Mono, auto-hospedadas, com números tabulares para nota,
timecode e duração pararem de dançar entre cards.

A barra de progresso que mentia (12% durante todo o download) virou trilha de
etapas com tempo decorrido; a barra só aparece onde existe fração de verdade.

---

## Três erros meus que valem registro

Estão aqui porque a correção só faz sentido junto do erro.

**A trava de custo tinha um buraco que deixou passar 18 GB.** A primeira versão
aceitava o job quando a consulta de metadados falhava — "um soluço de rede não
deve recusar trabalho legítimo". Mas consulta e download falham por motivos
diferentes: num teste real a consulta recusou um link de live e o download
gravou a transmissão. O caminho de escape do guarda era o caminho do vídeo caro.
Agora falha fechado.

**O teto do FFmpeg não matava o processo certo.** Matava só o líder; o filho
sobrevivia segurando o pipe e o `wait()` ficava preso — o abort levava 30 s em
vez dos 6 da carência. O teto contra travamento travava.

**Quebrei seu `next dev` por alguns minutos** ao rodar um build público sobre o
mesmo `.next`. Daí o `distDir` por variante.

---

## Checklist do deploy

Passo a passo em `docs/DEPLOY.md`.

### Antes de subir

- [ ] VPS com 4 vCPU / 8 GB / 80 GB+
- [ ] Pacotes de sistema, **incluindo** `libgl1 libglib2.0-0t64 libsm6 libice6 libxext6 libgomp1`
- [ ] Node 20+ e Python 3.11+
- [ ] Postgres criado (`docs/POSTGRES.md`)
- [ ] `make setup` e **`make update-ytdlp`** (a nightly, não a estável)
- [ ] `make emoji-font` (10 MB que não vão no git)

### Configuração

- [ ] `PUBLIC_BUILD=true`
- [ ] `DATABASE_URL` apontando para o Postgres, e `SQLITE_URL=` **vazia**
- [ ] `CLIPMINT_PASSWORD` gerada (`openssl rand -base64 24`)
- [ ] `ASSEMBLYAI_API_KEY` e `ANTHROPIC_API_KEY`
- [ ] Travas de custo revisadas
- [ ] `chmod 600 .env`

### Build e serviços

- [ ] `make build-public` **com o `BACKEND_PORT` final** (ele congela no build)
- [ ] `clipmint-api` e `clipmint-web` no systemd
- [ ] Nginx com `client_max_body_size 512M` e `proxy_read_timeout 600s`
- [ ] HTTPS pelo certbot
- [ ] **Marcar o cookie de sessão como `secure`** depois do HTTPS

### Conferir

- [ ] `/siege`, `/melhorar-video` e `/api/video-enhance` → 404
- [ ] `/api/jobs` sem sessão → 401
- [ ] `?source=siege` → 422
- [ ] `make db-current` diz `(head)`
- [ ] `grep -ril "siege" frontend/.next-public/static` → vazio
- [ ] Um vídeo curto de ponta a ponta, pelo navegador

### Rotina

- [ ] `pg_dump` no cron
- [ ] Alerta de espaço em disco
- [ ] `make update-ytdlp` ao primeiro 403

---

## O que falta para virar produto de verdade

Fora do escopo desta passada, em ordem de urgência.

**1. Pagamento.** Adiado por decisão sua. A cota por usuário já existe e é onde
um plano se encaixa.

**2. E-mail.** Sem recuperação de senha nem confirmação de cadastro.

**3. Monitoramento.** Só `journalctl`.

**4. Escala além de um servidor.** O pipeline roda dentro do processo da API com
lock por arquivo. Duas máquinas exigem fila de verdade e storage compartilhado.

**5. Decidir o provedor de transcrição.** A ferramenta está pronta; falta uma
chave do Deepgram e rodar a comparação nos seus vídeos.

### Dívidas menores, com destino

- Reuso de PID no `joblock` — fica barato de resolver agora que há Postgres
- `run_ffmpeg` acumula todo o stderr em memória
- Sub-progresso durante o download (a trilha já dá o tempo decorrido)
- 25 das 73 variáveis não estão no `.env.example` (são ajustes finos de visão,
  perícia e geometria do modo streamer, todos com padrão bom)
