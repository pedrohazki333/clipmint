# Decisões — preparação do ClipMint para produto público

Registro do que foi decidido, **por quê**, e o que foi deliberadamente NÃO
feito. A ordem é cronológica por fatia.

Quem lê isto depois costuma querer uma coisa só: saber se pode desfazer algo.
Por isso cada decisão traz o motivo e, quando existe, a medição que a sustenta.

---

## Contexto

O ClipMint nasceu como ferramenta local de uso pessoal. Esta passada prepara
uma versão pública, mantendo a pessoal intacta. Duas features continuam
evoluindo só na versão pessoal e não podem aparecer no produto:

- **Siege X** — nicho de análise de Rainbow Six Siege;
- **Melhorar vídeo** — tratamento local (upscale/interpolação/reencode) de
  vídeo enviado.

Restrições fixadas no início e respeitadas em tudo que segue: não quebrar o
pipeline existente, e **manter o `claude-sonnet-4-6` na análise de viralidade**.

---

## Fatia 1 — Separação público × pessoal

### D1. Um codebase com flag, não um branch `public`

**Decisão:** manter um único repositório e desligar as features por
`PUBLIC_BUILD`.

**Por quê:** o acoplamento das duas features ao miolo do pipeline é baixo —
nenhuma delas toca `clipper.py`, `facecam.py`, `layout.py`, `subtitler.py`.
Siege X é um *valor* de `source_type` mais um branch de HUD; Melhorar vídeo é
uma vertical isolada com router, model e worker próprios.

Um branch `public` teria que rebasear continuamente em cima dos arquivos
**compartilhados**, que é justamente onde o trabalho acontece — e cada rebase
reabriria conflito nos poucos pontos onde `siege` aparece. Divergência
permanente em troca de uma proteção que a flag já dá.

**Risco assumido:** deixar uma feature ligada por engano no público. Mitigado
por teste, não por disciplina: `backend/tests/test_public_build.py` sobe a API
com `PUBLIC_BUILD=true` e afirma 404 em cada endpoint e 422 em cada consulta
por `siege`.

### D2. Rotas do frontend saem por `pageExtensions`, não por `if`

**Decisão:** as páginas pessoais se chamam `page.personal.tsx`;
`pageExtensions` inclui `"personal.tsx"` só no build pessoal.

**Por quê:** um `if` deixaria o componente no bundle como código morto. Com
`pageExtensions`, o Next **não reconhece o arquivo como rota** — não compila,
não entra no manifesto. Confirmado no código do Next
(`leafOnlyPageFileRegex`, em `server/lib/find-page-file.js`) antes de adotar.

### D3. `NormalModuleReplacementPlugin`, e não `resolve.alias`

**Decisão:** no build público, `@/personal` é trocado pelo stub via
`NormalModuleReplacementPlugin`.

**Por quê:** o `resolve.alias` foi a primeira tentativa e **não funcionou** —
perde para o resolvedor de `paths` do tsconfig, que o Next instala como resolve
plugin. Descoberto rodando `grep -ril siege .next/`, que continuava achando o
módulo real. O plugin age depois da resolução e não depende dessa ordem.

**Como conferir:** `make build-public` e depois
`grep -ril "siege\|video-enhance" frontend/.next-public/static frontend/.next-public/server`
tem que voltar vazio.

### D4. `SourceTypeField` em vez de `Literal`

**Decisão:** o nicho é `str` com validação em tempo de request
(`app/features.py`), não um `Literal[...]`.

**Por quê:** a lista permitida depende do build, e um `Literal` é fixado no
import — não teria como encolher no público. Efeito colateral descoberto na
implementação: no FastAPI 0.115, `Annotated[...] = Query(...)` **descarta** a
metadata do pydantic; o `Query` precisa ficar *dentro* do `Annotated`. Sem
isso a validação passava batido em 3 dos 4 endpoints.

### D5. `distDir` por variante

**Decisão:** build público escreve em `.next-public`; pessoal, em `.next`.

**Por quê:** rodar `PUBLIC_BUILD=true npm run build` sobrescrevia o `.next` que
o `next dev` da versão pessoal estava usando, e o dev server passava a
responder 500 em toda página. Aconteceu ao verificar esta própria separação.

### D6. `"siege"` continua na união `SourceType` do TypeScript

**Decisão:** não remover o literal do tipo.

**Por quê:** tipo é apagado na compilação e não alcança o bundle; removê-lo
obrigaria a duplicar o arquivo por variante. Quem decide os nichos que
**existem** é a lista de `src/lib/features.ts`.

### D7. Resíduo aceito: `.hover:border-orange-500` no CSS público

**Decisão:** não remover.

**Por quê:** o Tailwind 4 varre `src/**` por texto, fora do grafo de módulos, e
gera a classe por causa do `accent` do Siege X. É uma cor genérica — não revela
nome, rota nem endpoint. Removê-la exigiria gerar o `globals.css` por variante,
custo desproporcional ao que ela expõe.

---

## Fatia 2 — Auditoria

17 achados. A divisão aprovada foi: corrigir agora o que quebra o fluxo
principal e as travas de custo/segurança; adiar para a Fatia 7 o que pertence
ao módulo de proteção de custo; adiar para a Fatia 9 o que é decisão de deploy;
e não corrigir três itens de baixo retorno.

### D8. Três itens NÃO serão corrigidos

| Item | Por que fica como está |
|---|---|
| Reuso de PID no `joblock` | Exige máquina muito carregada para acontecer. Resolver direito significa mover o lock para o banco — custo alto para um risco remoto. Reavaliar quando o Postgres entrar (Fatia 5), aí fica barato. |
| `run_ffmpeg` acumula stderr em memória | Limitado na prática: o stderr do FFmpeg num render de clipe fica na casa dos KB. |
| Sem sub-progresso no download | É trabalho de UI e rende mais junto com o polimento da Fatia 8. |

---

## Fatia 3 — Correções

### D9. Teto de tempo no FFmpeg, matando o GRUPO de processos

**Decisão:** `run_ffmpeg` e `probe_video` passam por
`asyncio.wait_for`; no estouro, `SIGTERM` no grupo, 5s de carência, `SIGKILL`.

**Por quê o teto:** sem ele o `communicate()` esperava para sempre. O job ficava
preso em `clipping`, o `DELETE` não interrompia o pipeline e o `retry` recusava
enquanto o lock estivesse vivo — a única saída era reiniciar o servidor.
Precedente no próprio projeto: a aba Melhorar vídeo já fazia isso certo
(`enhance_step_timeout`).

**Por quê o GRUPO, e não o processo:** a primeira versão matava só o líder, e o
filho dele continuava vivo segurando a ponta do pipe que estávamos lendo — o
`wait()` ficava preso esperando um EOF que não vinha. **Medido: 30s (a duração
inteira do filho) em vez dos 6s da carência.** Com `start_new_session=True` e
`os.killpg`, voltou a 6,01s. Guardado por
`tests/test_ffmpeg_timeout.py::test_filho_do_processo_tambem_morre`.

**Valores:** `ffmpeg_timeout=1800`, `ffprobe_timeout=120`. O teto existe para o
caso patológico, não para apertar o caso normal.

### D10. Excluir job em execução PARA o pipeline

**Decisão:** exceção `JobDeleted`, levantada por `_update_job_status` e por
`_abort_if_deleted` nos pontos caros; no desfecho, `_discard_storage` limpa o
que o processo recriou.

**Por quê:** excluir job em andamento é permitido de propósito — é a saída para
um job travado. O problema era o pipeline não perceber: seguia até o fim,
recriava os diretórios que o `DELETE` tinha apagado e inseria linhas de `Clip`
apontando para um job inexistente (o SQLite não aplica FKs, nada recusava).

**Evidência que motivou:** auditoria de 25/08/2026 no banco de desenvolvimento
— `PRAGMA foreign_keys = 0`, 9 transcrições órfãs e 0,32 GB de diretórios de
clips sem job correspondente.

**Qualidade do teste:** verificado desligando a correção — o teste falha com
"o laço renderizou 3 clips depois do DELETE".

### D11. Camada de tradução de erro (`app/errors.py`)

**Decisão:** `error_message` do job passa por `user_message(exc)`.

**Por quê:** antes ia `str(e)` direto para a tela — 2.000 caracteres de stderr
do FFmpeg, ou `ERROR: [youtube] xxx: Private video...` em inglês. O usuário não
entendia, e o interior do sistema vazava. O detalhe técnico continua inteiro no
log, que é onde serve.

**Regra ao acrescentar caso:** a frase tem que dizer o que aconteceu **e** o que
fazer. "Falha no download" não passa.

**Fallback genérico de propósito:** chutar uma causa errada é pior que admitir
que o detalhe está no log. Erro sem tradução vira `warning` pedindo que se
acrescente o caso se ele se repetir.

### D12. `stop_reason == "max_tokens"` detectado explicitamente

**Por quê:** caía no `except json.JSONDecodeError` e virava "Claude returned
invalid JSON" — mandava investigar o parser quando o problema era o
`claude_max_tokens`.

### D13. Coluna `jobs.result_note`

**Decisão:** o backend grava POR QUE um job terminou sem clips; a tela mostra
essa nota.

**Por quê:** a tela afirmava sempre *"Nenhum trecho atingiu o threshold"*, mas
"zero clips" tem mais de uma causa — nota abaixo do mínimo, todos os candidatos
descartados pelo HUD, e (a partir da Fatia 7) vídeo sem fala. Afirmar a causa
errada é pior que não afirmar nenhuma.

**Por que uma coluna, e não uma mensagem genérica:** a genérica seria o
conserto de uma linha, mas a informação útil — *qual* foi o motivo — é
exatamente a que se perderia. Usa o mecanismo de migração que o projeto já tem
(`_ADDED_COLUMNS`).

### D14. Upload lido em pedaços, com o teto valendo durante a leitura

**Decisão:** `_stage_clip` grava em arquivo temporário em pedaços de 1MB e
aborta no pedaço que estoura os 500MB.

**Por quê:** a versão anterior fazia `await clip.read()` e só **depois**
comparava com o teto — que portanto não protegia de nada: um upload de 2GB já
estava inteiro na memória quando era recusado. Num VPS pequeno com mais de um
usuário, é o caminho mais curto para o OOM.

**Guardado por:** `tests/test_upload_streaming.py` afirma que oferecer 200MB com
teto de 3MB entrega no máximo ~5MB antes da recusa.

### D15. Build público recusa subir sem `CLIPMINT_PASSWORD`

**Decisão:** `RuntimeError` no startup quando `PUBLIC_BUILD=true` e a senha
está vazia. A versão pessoal continua subindo sem senha.

**Por quê:** a guarda de acesso do middleware só age **quando há senha**. Sem
ela, nenhuma checagem acontece — o backend falhava *aberto* enquanto o
frontend já falhava *fechado* (503). A assimetria era o furo: quem apontasse
direto para a API passava por cima da tela de login e disparava jobs que
gastam crédito de AssemblyAI e Anthropic.

**Por que no startup, e não no primeiro request:** um servidor que não sobe é
um problema visível; um servidor aberto não é.

**Por que a pessoal fica de fora:** é ferramenta local, a porta só escuta em
`127.0.0.1` no `make serve`, e passar a exigir senha quebraria o uso diário.

### D16. Um regex de URL, verificado nos dois lados

**Decisão:** o regex do frontend (`src/lib/youtube.ts`) é cópia literal do
`_YOUTUBE_URL_RE` do backend, e um teste **compara os dois caractere a
caractere**.

**Por quê:** eles tinham divergido em 5 dos 8 casos medidos. O front recusava
`youtube.com/shorts/` e `/live/` que o backend aceita (link válido morria na
tela) e aceitava `www.youtube.com/watch?v=x` sem esquema e até
`https://evil.com/?redir=youtube.com/watch?v=x`, que o backend recusava com 422
depois do submit.

**Por que não compartilhar o regex de verdade:** um é Python, outro é
TypeScript. A duplicação é o preço de validar nos dois lados; o que dá para
eliminar é a *chance de divergirem*, e é isso que o teste faz —
`test_os_dois_regexes_sao_o_mesmo_texto`. Mexer num lado sem o outro quebra a
suíte.

### D17. 404 encerra o polling; erro de rede não

**Decisão:** a tela do job distingue "não existe mais" (definitivo, para o
polling, oferece voltar) de "falhou ao carregar" (transitório, segue tentando).

**Por quê:** antes, qualquer erro deixava o polling rodando a cada 3s para
sempre — inclusive num job apagado, que nunca vai voltar.

---

## Fatia 4 — Provedor de transcrição plugável

### D18. Fachada + registro, não `if` no pipeline

**Decisão:** `services/transcription/` com um contrato
(`TranscriptionProvider`), um provedor por arquivo e um registro em
`__init__.py`. O pipeline continua chamando `transcribe_audio(job_id, path)` e
não sabe quem respondeu.

**Por quê:** os dois consumidores (`pipeline.py` e `reference_pipeline.py`) não
mudaram uma linha. Acrescentar um terceiro provedor amanhã é um arquivo novo
mais uma linha no registro.

### D19. Pós-processamento fica na FACHADA, não no provedor

**Decisão:** a limpeza de repetições degeneradas
(`postprocess.drop_degenerate_repeats`) saiu de dentro do AssemblyAI e passou a
valer para qualquer provedor.

**Por quê:** travar numa palavra e cuspir dezenas de cópias é defeito de
decodificador, não de fornecedor — não há razão para supor que o Deepgram seja
imune. E, mais importante para esta fatia: se a limpeza ficasse dentro de um
provedor, **a comparação estaria medindo o pós-processamento em vez dos
modelos**.

Pelo mesmo motivo, a gravação do JSON de palavras também é da fachada: é
artefato do pipeline, não do fornecedor.

### D20. Deepgram falado por httpx, sem o SDK oficial

**Por quê:** o pré-gravado do Deepgram é **um único POST**; o SDK não esconderia
complexidade nenhuma e traria uma árvore de dependências nova. httpx já é
dependência do projeto. Como efeito colateral bom, os parâmetros ficam
explícitos no código — inclusive o `multichannel=false`.

O áudio é enviado em fluxo, lido do disco em pedaços: um WAV mono 16 kHz de duas
horas tem ~230 MB, e carregá-lo inteiro para mandar seria repetir o erro do
upload de referência (D14).

### D21. `multichannel=false` explícito nos dois — e o que isso NÃO era

**Decisão:** os dois provedores recebem o parâmetro de canal único explícito.

**Ressalva honesta:** isto **não corrigiu uma cobrança em dobro**, porque ela
não estava acontecendo. O áudio já sai mono do FFmpeg (`-ac 1` em
`services/downloader.py`), então nunca houve dois canais para cobrar. O
parâmetro explícito é precaução para o dia em que a origem do áudio mudar — aí
a conta subiria sem ninguém entender por quê.

### D22. As métricas da comparação são as deste projeto, não um benchmark genérico

**Decisão:** o relatório mede fração de palavras abaixo de 0,7 de confiança,
maior sequência repetida, e fração de palavras sem duração própria — além de
tempo, custo e o texto.

**Por quê:** são exatamente os três defeitos que já apareceram em material real
e estão registrados em `config.py`: o universal-2 alucinou em grito (46% abaixo
de 0,7, contra 9% do universal-3-5-pro); o universal-3-5-pro travou repetindo
"não" 128 e 121 vezes; o universal-3-pro devolveu um terço das palavras sem
duração própria, o que estraga a legenda karaokê. Um WER genérico não
distinguiria nenhum dos três.

As medições rodam sobre o texto **bruto** do provedor, antes da limpeza — ver
D19.

### D23. Comparação é script de linha de comando, não rota nem passo do pipeline

**Por quê:** rodar dois provedores custa o dobro. Isso tem que ser um ato
deliberado de quem está avaliando, nunca algo que aconteça por acidente num job
comum. Os provedores rodam **em sequência**, não em paralelo: o tempo de
processamento é uma das medidas, e duas transcrições disputando rede e CPU
mediriam a disputa.

### D24. Tarifas em configuração, com data de consulta

**Decisão:** `ASSEMBLYAI_COST_PER_HOUR` e `DEEPGRAM_COST_PER_HOUR` no `.env`,
com a tabela e a data no comentário de `config.py`.

**Por quê:** preço de fornecedor muda, e um número cravado no código vira
mentira silenciosa dentro de um relatório que serve justamente para decidir por
custo.

**Dado que muda a leitura da decisão:** pela tabela de 25/08/2026, o Deepgram
nova-3 (US$ 0,258/h) é **~23% mais caro** que o AssemblyAI universal-3-pro
(US$ 0,21/h). A troca não é economia — só se justifica por qualidade.

---

## Fatia 5 — Postgres, Alembic e usuários

### D25. Os dois dialetos convivem: SQLite na pessoal, Postgres no público

**Decisão:** `DATABASE_URL` aceita os dois. O build público **recusa subir** em
SQLite; a versão pessoal continua em SQLite.

**Por quê manter o SQLite:** a versão pessoal roda no WSL2 e é usada todo dia;
exigir um Postgres no laptop para clipar um vídeo seria custo sem contrapartida.
E os 479 testes rodam em arquivo temporário, sem serviço externo — passar a
exigir um Postgres para rodar a suíte tornaria o ciclo de trabalho mais lento
todos os dias em troca de nada.

**Por quê recusar SQLite no público:** um arquivo com um escritor por vez, num
servidor com vários usuários e jobs concorrentes, dá corrupção e "database is
locked" no meio de um render. Mesma lógica da senha (D15): falhar no startup,
onde é visível.

**Risco assumido:** o schema roda em dois dialetos, e uma diferença entre eles
pode passar pelos testes. Mitigado por escrever as migrações em modo `batch`
(que o SQLite exige e o Postgres ignora) e por `compare_type=True` no
autogenerate. Não elimina o risco — a verificação em Postgres real é passo
obrigatório antes do deploy.

### D26. Alembic substitui o `ALTER TABLE` manual

**Decisão:** a lista `_ADDED_COLUMNS` de `database.py` saiu; migrações são do
Alembic.

**Por quê:** ela só falava SQLite. O tipo `DATETIME` que emitia **não existe no
Postgres** — a primeira migração num servidor de verdade teria falhado. Era um
bug latente, apontado na auditoria da Fatia 2.

**Baixa do backfill:** junto foi o backfill de `source_type` a partir de
`layout_mode`. Antes de aposentá-lo, conferi que não tinha mais trabalho: **0
linhas pendentes** tanto no banco atual quanto no backup de 13/08/2026, e os
dois já com a coluna. O teste que o cobria foi reescrito para guardar a REGRA
que continua viva (`default_source_type`), em vez da migração morta.

### D27. Duas migrações, não uma — e o carimbo automático

**Decisão:** `0001_schema_inicial` descreve o banco **como ele já era**;
`0002_usuarios` acrescenta `users` e `jobs.user_id`. No startup, um banco que
tem tabelas mas não tem `alembic_version` é carimbado como 0001 e segue dali.

**Por quê:** existem bancos anteriores ao Alembic. Para ele, um banco assim está
na estaca zero — e `upgrade head` tentaria `CREATE TABLE jobs`, que já existe, e
**o servidor não subiria**. A separação é o que torna o carimbo possível: se
`users` estivesse dentro da 0001, carimbar pularia a criação dela.

**Por que automático:** a alternativa é um passo manual documentado que alguém
esquece, e o sintoma (servidor não sobe) aparece no pior momento.

**Verificado:** contra uma cópia do banco de desenvolvimento real — carimbou,
aplicou a 0002, e as 9 transcrições, 1 referência e 4 linhas da tabela órfã
continuaram lá.

### D28. `model_video_jobs` é ignorada pelo Alembic

**Decisão:** `IGNORAR_TABELAS` em `migrations/env.py`.

**Por quê:** essa tabela existe no banco com **4 linhas dentro**, resquício da
geração de vídeo pelo Veo que foi abandonada, e não tem modelo em `models.py`.
Sem o filtro, o `--autogenerate` proporia `DROP TABLE` nela e a migração apagaria
dado real sem avisar. Guardado por teste.

### D29. `jobs.user_id` nasce NULO permitido

**Por quê:** os jobs que já existiam não têm dono, e inventar um seria pior que
admitir a ausência. Job sem dono só aparecerá para quem administra.

O índice composto `(user_id, created_at)` existe porque "meus jobs, do mais novo
para o mais velho" é a consulta mais repetida do produto — todo polling da tela
de conta passa por ela.

### D30. `users` entra agora, o login só na Fatia 6

**Decisão:** o schema de usuários nasce nesta fatia; cadastro, login e sessão
ficam para a seguinte.

**Por quê:** o banco tem que nascer certo **de uma vez**. Adicionar `users`
depois do Postgres já estar em produção seria uma segunda migração num sistema
com dados reais — barato agora, caro depois.

### D31. psycopg 3, não psycopg2 nem asyncpg

**Por quê:** o psycopg 3 fala síncrono **e** assíncrono. A aplicação é async e o
Alembic é sync; com asyncpg seriam dois drivers para instalar, configurar e
manter em sincronia.

### D32. A URL do banco não fica no `alembic.ini`

**Por quê:** o `.env` da raiz é a fonte única de configuração do projeto (mesma
regra que já valia para a porta do backend). Uma segunda cópia da URL acabaria
aplicando migração no banco errado — erro que só se descobre tarde.

### D33. O script de cópia nunca modifica a origem

**Decisão:** `app.scripts.migrate_to_postgres` abre o SQLite só para ler, recusa
destino que já tenha linhas, e confere a contagem no fim.

**Por quê:** migrar não é mover. Se algo der errado no meio, o SQLite tem que
continuar sendo a cópia boa. E copiar por cima de tabela com conteúdo duplicaria
linha e violaria chave primária no meio do caminho, deixando o banco pela metade.

### D34. Órfãos: o script detecta antes, e a cópia é tudo-ou-nada

**Descoberto testando em Postgres real**, não por leitura. A primeira cópia dos
dados morreu com `ForeignKeyViolation`: as 9 transcrições órfãs da auditoria da
Fatia 2 apontam para jobs que não existem. **O SQLite não aplica chave
estrangeira; o Postgres aplica.** Linha que convive em paz no arquivo de origem
derruba a migração no meio — e isso teria acontecido no dia do deploy.

**Decisão:** o script confere as referências ANTES de escrever (inclusive no
`--dry-run`, que é onde se quer descobrir), explica o problema e oferece
`--pular-orfaos`. E a cópia virou **uma transação só**: um commit por tabela
deixaria o destino pela metade se a terceira falhasse, e um banco meio migrado é
pior que nenhum, porque parece pronto.

**Por que não apagar os órfãos aqui:** são dados do dono do projeto, e a limpeza
ficou combinada para a Fatia 7, junto do TTL. O script tem que conviver com eles,
não decidir por conta própria.

### D35. A validação de URL passa a exigir o identificador do vídeo

**Descoberto na mesma verificação.** `https://youtu.be/` passava nos dois
validadores **e** no `extract_info` do yt-dlp — que resolve o endereço para uma
URL sem id nenhum, sem levantar erro. O resultado era um job criado, que baixava
nada e falhava com uma mensagem que não explicava coisa alguma.

**Decisão:** os dois regexes (que o teste de paridade mantém idênticos) passam a
exigir pelo menos um caractere de id depois de `youtu.be/`, `shorts/`, `live/` e
`v=`.

**O tamanho do id NÃO é validado**, de propósito: hoje são 11 caracteres, mas
quem tem autoridade para dizer se um id existe é o YouTube, não um regex nosso.
O que se recusa é o endereço vazio, que nunca vai a lugar nenhum.

### D36. Verificação em Postgres real é passo obrigatório, não opcional

Esta fatia é a evidência. Os 479 testes passavam, o SQLite ia bem, o banco
legado migrava — e **duas falhas reais só apareceram contra um Postgres de
verdade** (D34 e D35). A checagem de dialeto por teste é necessária e não é
suficiente.

---

## Fatia 6 — Autenticação

### D37. Duas portas, um só conceito de usuário

**Decisão:** o build público tem contas (e-mail e senha); a versão pessoal
continua com a senha única. Nas duas, `current_user` devolve um `User`, e
nenhuma rota pergunta em qual build está.

**Por quê:** passar a exigir cadastro na versão pessoal quebraria o uso diário
sem ganho nenhum — é uma pessoa, numa máquina. Mas o resto do sistema (cota da
Fatia 7, TTL, isolamento) fala em usuário. O encaixe é o **usuário-dono**:
existe UM, semeado no startup, e todos os jobs são dele.

### D38. Sessão no banco, não JWT

**Por quê:** sessão em token assinado não dá para revogar antes de expirar. Com
a tabela, "sair de todos os aparelhos" e "desativar a conta" são um DELETE que
vale na hora — e os dois estão cobertos por teste. O custo é uma consulta por
request, por chave primária.

**O que se guarda é o HASH do token, nunca o token.** Um dump ou backup vazado
não permite se passar por ninguém. E o hash é SHA-256, rápido, ao contrário do
das senhas: o token tem 256 bits vindos do `secrets`, não há o que adivinhar, e
um hash lento só encareceria cada request.

### D39. Argon2id, e a senha só tem regra de tamanho

**Por quê Argon2id:** é a primeira escolha da OWASP e, ao contrário do bcrypt,
não trunca em 72 bytes — um limite silencioso que faria uma senha longa valer
só pelo começo. Medido: ~76 ms por hash.

**Por quê só tamanho (12 caracteres):** exigência de composição ("uma maiúscula
e um símbolo") empurra as pessoas para `Senha@123`, que é pior que uma frase
longa. É a recomendação atual da OWASP.

O `check_needs_rehash` regrava a senha no próximo login quando os parâmetros do
Argon2 subirem — sem pedir nada a ninguém e sem invalidar quem não entrou ainda.

### D40. Recurso de outra pessoa responde 404, nunca 403

**Por quê:** um 403 confirmaria que aquele id existe, e daria para varrer ids
descobrindo o que os outros estão processando. Para quem não é dono, o recurso
simplesmente não existe.

O caso grave é o `/clips/{id}/download`: ele entrega o arquivo de vídeo, que é o
produto inteiro. O clip não guarda dono — quem guarda é o job —, então a
checagem é uma junção com `jobs`; sem ela, um id adivinhado daria o trabalho de
alguém para outro.

### D41. Job sem dono: visível na pessoal, invisível no público

**Decisão:** `owned_by(user)` monta a condição de propriedade e ela difere por
build — no pessoal inclui `user_id IS NULL`.

**Por quê:** na versão pessoal existe UM usuário, então job sem dono é dele; não
há de quem mais pudesse ser. O startup adota os órfãos, mas depender só disso
deixaria a pessoa sem enxergar os próprios jobs se a adoção não tivesse rodado.
No público, atribuir um job órfão a alguém seria inventar — ele fica invisível.

### D42. Presets de marca ficam restritos a quem administra — e isso é uma DÍVIDA

**Decisão:** no build público, as rotas de `/api/settings/*` exigem `is_owner`.

**Por quê agora:** os presets são gravados por NICHO, num diretório
compartilhado. Sem a trava, no produto público a logo de um usuário apareceria
no clipe do outro — e poderia ser sobrescrita por ele. Era um buraco que a
própria multiusuário criava.

**Por que não resolver de vez:** o certo é branding POR USUÁRIO
(`storage/branding/<user_id>/<nicho>/`), mas `preset_path` é chamado de dentro
do caminho de render (`clipper` → `watermark`/`layout`), e levar o `user_id` até
lá é cirurgia no pipeline — justamente o que não podia ser tocado nesta passada.

**Consequência assumida, e ela é séria:** no produto público, **usuário comum
não consegue colocar a própria marca nos clipes**. Isso precisa ser resolvido
antes de um lançamento de verdade, e não está em nenhuma fatia deste plano.

### D43. `BACKEND_PORT` é congelado no build do frontend

**Descoberto na verificação ao vivo.** O `rewrites()` do Next é avaliado em
tempo de BUILD e gravado no `routes-manifest.json` — passar `BACKEND_PORT` só na
hora de subir o servidor não tem efeito, e o proxy continua apontando para a
porta que valia quando o build foi feito. Está no `docs/POSTGRES.md` e vai para
o guia de deploy.

---

## Fatia 7 — Travas de custo e retenção

### D44. Toda guarda roda ANTES do download

**Decisão:** duração, cota e duplicata são conferidas na resposta do
`POST /jobs`, com uma consulta de metadados (barata) antes do download (caro).

**Por quê:** recusar depois de baixar e transcrever já teria custado exatamente
o que a guarda existe para evitar.

O job nasce com a duração já medida, e isso não é detalhe: a cota soma a duração
dos jobs da janela, então sem gravá-la na criação **dez pedidos disparados juntos
passariam todos**, porque nenhum teria duração registrada ainda.

### D45. A guarda de custo falha FECHADO — a lição mais cara da fatia

**A primeira versão estava errada.** Ela deixava o job passar quando a consulta
de metadados falhava, com o raciocínio de que um soluço de rede não devia
recusar trabalho legítimo.

O erro: **consulta e download falham por motivos diferentes.** Testando ao vivo
com um link de live real, a consulta devolveu
`This live stream recording is not available` — e o download logo em seguida
funcionou perfeitamente, gravando a transmissão. **18 GB em disco antes de eu
perceber.** O caminho de escape do guarda era justamente o caminho que o vídeo
caro percorria.

**Agora:** havendo teto, vídeo de duração desconhecida é recusado. Sem teto (a
versão pessoal), segue permissivo — lá quem manda o link paga por ele.

### D46. Transmissão ao vivo é recusada nas duas versões

Live não tem duração, então escapa do teto; e o yt-dlp apontado para uma começa
a **gravá-la**, sem fim previsto. A recusa não é questão de quem paga — o
produto não sabe fazer isso. Gravação de live já encerrada (`was_live`) tem
duração e passa normalmente; live agendada (`is_upcoming`) também é recusada.

### D47. Cota e teto têm padrões DIFERENTES por build

Mesma forma do resto do projeto: `QUOTA_*` e `MAX_SOURCE_MINUTES` vêm em 0
(desligados) e o build público cai em `PUBLIC_*`.

**Por quê:** na versão pessoal é uma pessoa, na própria conta de API,
processando uma live de 6h de propósito — uma cota ali atrapalharia o trabalho
sem proteger ninguém. No público, quem paga a conta não é quem manda o link, e
isso muda tudo. Um teste chegou a falhar por eu ter esquecido essa diferença.

### D48. Janela deslizante, não dia-calendário

Com "por dia", quem estoura às 23h volta a ter tudo às 00h — e o pico de abuso
cabe em duas horas.

### D49. Duplicata só barra o que está EM ANDAMENTO

Dois cliques custavam dois downloads e duas transcrições do mesmo vídeo.
Reprocessar um vídeo já concluído continua permitido: mudou o preset, mudou o
modo de legenda, é pedido legítimo.

### D50. TTL apaga ARQUIVO, nunca a linha do banco

**Decisão:** clipe vencido vira `status='expired'` com `file_path=None`. Nota,
eixos da rubrica, o que foi aprendido e o desempenho real depois de postado
ficam.

**Por quê:** são eles que alimentam o few-shot. Apagá-los destruiria o
aprendizado do sistema para economizar bytes que não são deles — os bytes são
do arquivo.

O vídeo de ORIGEM sai bem antes (3 dias contra 14): é o que ocupa GB de verdade
e só serve para re-renderizar. Depois de apagado, "Retomar" continua funcionando
— só volta a baixar.

### D51. A faxina não toca em pasta com nome de gente

**Decisão:** só apaga pasta cujo nome é um id de job (32 hex).

**Por quê:** o storage de desenvolvimento tinha `86aebb59_pre-correcao-1603` e
`..._pre-reanalise-20260817` — backups manuais feitos antes de mexer em algo. A
primeira versão da limpeza os teria apagado. Nome fora do padrão significa que
uma PESSOA batizou aquilo, e pessoas nomeiam o que querem guardar.

### D52. A faxina roda dentro do servidor, com escape para cron

**Por quê dentro:** um servidor que exige um passo manual de instalação para não
encher o disco acaba enchendo o disco. E disco cheio não degrada, ele PARA.

`CLEANUP_INTERVAL_HOURS=0` desliga, para quem preferir cron
(`python -m app.scripts.cleanup`). O laço nunca morre por exceção: faxina que
para de rodar em silêncio é pior que faxina que erra uma vez.

### D53. Vídeo sem fala não paga a análise

Transcrição vazia montava um prompt válido e ia para a API — chamada paga para
perguntar sobre um texto que não existe — e a tela ainda dizia "nenhum trecho
atingiu o threshold", explicação falsa. Agora o job termina com a nota certa em
`result_note` (D13).

### D54. Testes não falam com o YouTube

A consulta de metadados fez a suíte inteira sair para a rede: 24 s mais lenta,
dependente de conexão, e URLs de mentira viravam 422 por motivo alheio ao que
estava sendo testado. Um fixture `autouse` no conftest devolve metadados vazios;
quem testa os tetos sobrescreve.

---

## Fatia 8 — Refino visual

### D55. Tokens num arquivo só, e o app deixa de ser "tema escuro padrão"

**Medido antes de decidir:** 14 cinzas soltos em ~380 usos, 5 raios de borda
para o mesmo papel, e `text-sm` + `text-xs` somando **212 dos 244** usos de
tamanho — tudo tinha o mesmo peso e nada guiava o olho. Nenhuma fonte estava
definida: o app rodava na fonte padrão do navegador.

Agora: 3 superfícies, 3 níveis de texto, 3 raios, escala de 5 degraus, tudo em
`globals.css`. Os neutros levam um traço de verde do próprio acento — sutil de
propósito: quem usa não deve notar a escolha, só sentir que o app tem dono.

### D56. IBM Plex Mono para número, e o motivo não é estético

Timecode, duração, as cinco notas da rubrica e a contagem de views aparecem em
**cards repetidos**. Com dígitos de largura proporcional eles dançam de uma
linha para outra e a nota `8.4` pula de posição a cada card. `tabular-nums`
resolve. É leitura em coluna, não decoração.

Pelo `next/font` as fontes são hospedadas junto do app — verificado no build:
16 arquivos `.woff2` locais, nenhuma requisição a terceiros.

### D57. A barra de progresso mentia, e foi substituída

A anterior usava pesos fixos por etapa (`STAGE_PROGRESS`): **12% durante todo o
download**, pulsando parada por vinte minutos, e o mesmo número para um vídeo de
três minutos e para uma live de seis horas.

**Agora a barra só aparece onde existe uma fração de verdade** — em "gerando
clipes" sabemos 2 de 5. Nas outras etapas mostramos o que realmente se sabe:
qual etapa roda e há quanto tempo, com o tempo das concluídas à vista.

**Isso exigiu backend.** Os tempos por etapa não existiam; sem registrá-los,
"Download 4:12" seria invenção — trocar uma mentira por outra. Daí a coluna
`jobs.stage_log` (migração 0004), append-only: a duração de uma etapa é a
diferença até a marca seguinte, então nenhuma escrita precisa saber qual era a
etapa anterior, e um job retomado soma as passagens em vez de sobrescrever.

O `ReferenceStatus` tinha a mesma barra fixa e recebeu o mesmo tratamento — mas
**sem tempos**, porque o pipeline de referência não os registra. Mostrar só as
etapas ali é o honesto; inventar duração seria repetir o erro.

### D58. Duas falhas silenciosas viraram mensagem

- `SchedulePanel` fazia `setSlots([])` no erro, e falha de rede ficava
  **idêntica** a "nenhum horário na grade": a tela dizia "0 de 0" e ninguém
  sabia se o problema era o servidor ou a configuração.
- `JobCard` engolia o erro de exclusão: a pessoa clicava, nada acontecia, nada
  explicava.

Os outros 16 `catch` ou já mostravam erro ou têm o silêncio justificado por
comentário (painel secundário cujo erro real aparece na própria página).

### D59. O gancho perdeu o fundo amarelo

Ele competia com a nota, que também é amarela na faixa média — dois amarelos
disputando atenção no mesmo card. Virou um filete verde à esquerda: marca a
citação sem disputar.

### D60. Rótulos passam a dizer o que fazem, em português

`score` → `nota`, `Download MP4` → `Baixar MP4`, `Falha ao processar este clip`
→ uma frase que diz o que fazer em seguida. O resto da interface está em
português, e o rótulo de um controle deve nomear o que acontece ao clicar.

### D61. O que ficou de fora

Layout das telas, fluxo e a estética dos clipes gerados (`layout.py`) não foram
tocados — o brief pediu refino, não redesign, e a memória do projeto registra
que a estética @gazeclips foi implementada e rejeitada.

---

## Fatia 9 — Documentação de deploy

### D62. O segredo sai do artefato público

**Descoberto conferindo o build.** O `env` do `next.config` é *inlined* em tempo
de build, e a `CLIPMINT_PASSWORD` ficava dentro do bundle do SERVIDOR — inclusive
no build público, que não a usa para nada (lá quem autentica é a sessão).

Ao cliente ela nunca chegou (verificado nos dois builds). Ainda assim, assar um
segredo num artefato que não precisa dele é superfície de graça.

**Agora:** a senha só é injetada no build pessoal, e as rotas `/auth/login` e
`/auth/logout` viraram `route.personal.ts` — no público elas simplesmente não
existem. Mesmo mecanismo das páginas, e o `pageExtensions` do Next já cobre
`route` além de `page`.

### D63. Duas coisas congelam no build do frontend, e isso vai na documentação

`BACKEND_PORT` (o proxy é resolvido em build-time e gravado no
`routes-manifest.json`) e `CLIPMINT_PASSWORD` no build pessoal. Mudar qualquer
uma e só reiniciar não tem efeito — descoberto testando, não lendo a
documentação do Next. Está em destaque em `docs/DEPLOY.md`.

### D64. As bibliotecas de sistema foram verificadas, não presumidas

`libgl1 libglib2.0-0t64 libsm6 libice6 libxext6 libgomp1` — extraídas com `ldd`
sobre os `.so` do OpenCV e do MediaPipe e mapeadas para pacotes com `dpkg -S`,
em vez de copiadas de um tutorial. Sem elas o `import cv2` falha com
`libGL.so.1: cannot open shared object file`, erro difícil de associar à causa.

### D65. A documentação diz o que o produto ainda NÃO faz

`docs/DEPLOY.md` e `docs/RESUMO.md` terminam com os limites do que foi entregue:
branding por usuário (que bloqueia o lançamento), ausência de pagamento e de
e-mail, um servidor só, sem monitoramento. Um guia de deploy que só lista o que
funciona deixa quem for usá-lo descobrir os buracos sozinho, em produção.

---

## Fatia 10 — Reorganização por perfis

### D66. `Profile` é entidade nova, e isso foi decisão consciente

O pedido original dizia "não crie novas entidades". Mas a tela "Criar novo
perfil", com nome livre e ícone escolhido, **não existe sem persistência nova**:
antes, "conta" era um valor de enum (`podcast` | `gameplay` | `siege`) escrito em
`app/features.py`, com uma pasta de presets no disco. Não havia onde guardar
"HZ Pod Clips".

O conflito foi apresentado antes de qualquer código, e a escolha foi criar a
entidade. Migração 0005.

### D67. O perfil FORNECE o nicho; o job GRAVA

**É a fronteira mais importante desta fatia.** `jobs.source_type` continua sendo
o que o pipeline lê — analyzer, clipper, layout, watermark e cronograma não
foram tocados. O perfil só preenche esse valor na criação.

**Por que importa:** se o pipeline lesse `profile_id`, editar um perfil
reescreveria a rubrica de vídeos já analisados, e excluir um perfil deixaria
jobs órfãos sem rubrica nenhuma. Três testes guardam isso — inclusive um que
edita o perfil e confere que o job antigo não mudou.

### D68. `jobs.profile_id` é nulo permitido

Mesma razão do `user_id` (D29): os jobs anteriores não têm perfil, e inventar um
seria pior que admitir a ausência. O filtro por `source` continua na API ao lado
do filtro por `profile_id` — é como esses jobs seguem alcançáveis.

### D69. Excluir perfil não apaga vídeo

Os jobs e clipes ficam, com `profile_id` nulo. O perfil é a configuração; o job
é o trabalho. Apagar os vídeos junto seria destruir trabalho para remover uma
preferência.

### D70. A semeadura só cria nicho que a pessoa usou

Quem nunca gerou gameplay não ganha um perfil de gameplay vazio. Idempotente,
roda a cada startup na versão pessoal, e liga os jobs antigos por `source_type`
— nenhum job muda de conta, ele só passa a ter um perfil que o aponta.

### D71. O que do wireframe NÃO virou funcionalidade

Seguindo a regra de não transformar elemento visual em requisito:

| No wireframe | Por que ficou de fora |
|---|---|
| Nicho "Entrevistas" | Não é uma rubrica que existe. Vira um perfil chamado "Cortes de Entrevistas" com base Podcast. |
| Avatar por upload | Upload de imagem é funcionalidade nova. O avatar é uma chave de ícone. |
| Quantidade de clipes | Não existe por job neste sistema. |
| Duração do clipe | É configuração global (`.env`), não por job. |
| Idioma da legenda | Idem. |
| Miniaturas, player, download em massa | Não existem. |

### D72. As rotas antigas de conta viraram redirecionamento

`/podcast`, `/gameplay` e `/siege` continuam existindo e levam ao perfil daquela
rubrica. Link salvo e aba aberta não podem quebrar por causa de uma
reorganização. Sem perfil correspondente, a tela oferece criar um — não inventa.

### D73. Nunca apagar `.next` com o `next dev` rodando

Quebrei o dev server do dono do projeto pela SEGUNDA vez com isso — a primeira
foi na Fatia 1 (D5), e o `distDir` por variante resolveu o caso do build
concorrente, mas não o `rm -rf .next` manual. Depois de apagado, o `next dev`
não se recupera: fica servindo 404 e depois para de escutar a porta. A saída é
reiniciar o processo.

---

## Fatia 11 — Marca por perfil (a dívida D42, quitada)

### D74. O escopo virou o PERFIL, não o usuário

Quando registrei a D42, a ideia era `storage/branding/<user_id>/`. Com perfis
existindo, isso ficou errado pela metade: dois perfis da MESMA rubrica — "HZ Pod
Clips" e "Cortes de Entrevistas", ambos podcast — continuariam dividindo a
mesma logo. O escopo certo é o perfil.

### D75. Duas escalas, e a diferença é quem escreve

- **Perfil** (`profile_id`): é do usuário. Qualquer um mexe nos presets dos
  próprios perfis. Foi isto que quitou a dívida — antes, no build público,
  usuário comum não conseguia pôr marca nenhuma nos clipes.
- **Nicho** (sem `profile_id`): compartilhado pela instalação, e por isso segue
  restrito a quem administra. Serve de padrão para quem não subiu a própria.

### D76. Ler cai no nicho; escrever nunca cai

`preset_path` (leitura) devolve o arquivo do perfil se existir, senão o do
nicho — é essa queda que faz perfil recém-criado já sair com marca, e job antigo
(sem perfil) renderizar exatamente como antes.

`_destino` (escrita) **nunca** cai. Se a escrita usasse o caminho de leitura,
salvar a marca de um perfil gravaria por cima do preset da instalação inteira.
Guardado por `test_salvar_no_perfil_nao_sobrescreve_o_do_nicho`.

### D77. `profile_id` atravessa o render com default None

O caminho `clipper → watermark/layout` ganhou um parâmetro opcional em cada
função de marca. Com `None`, o comportamento é byte a byte o de antes — nenhuma
chamada existente precisou mudar, e é isso que torna a mudança segura dentro do
código que eu tinha me comprometido a não quebrar.

Confirmado que no render `source_type` era usado **só** para localizar preset:
por isso a mudança ficou contida em 8 assinaturas e nenhuma lógica de vídeo.

### D78. Id de perfil é validado antes de virar caminho

`profile_id` chega de um parâmetro de request e vira nome de diretório. Sem o
`^[0-9a-f]{32}$`, um `../` sairia da pasta de branding. Guardado por teste.

### D79. Excluir perfil leva os presets dele

Sem isso, cada perfil excluído deixava uma pasta de imagens que nada mais
apontava — encontrado na verificação ao vivo, não por leitura. Os clipes já
renderizados não mudam: a marca foi queimada no vídeo na hora do render.

---

## Fatia 12 — Aprendizado sai do build público

### D80. As três peças do aprendizado são uma só decisão

Aprender com clipe viral (`/api/references/*`), os padrões minerados deles
(`/api/patterns/*`) e "Salvar exemplo" no card do clipe
(`POST /api/clips/{id}/validate`). O pedido nomeou as duas primeiras; a terceira
entrou porque **alimenta a mesma pasta**.

**O motivo é mais forte que "feature interna".** Os exemplos validados vão todos
para `prompt_engine/examples/validated/`, uma pasta ÚNICA que o `PromptBuilder`
injeta na análise de TODO job. Liberado no público, o exemplo de um usuário
passaria a influenciar o corte dos outros — inclusive os do dono da instalação.
É o mesmo vazamento de estado compartilhado que os presets de marca tinham antes
de virarem por perfil (D74).

Hoje são 9 exemplos na pasta, todos do dono.

### D81. `validate` responde 404 em vez de sair do router

As rotas de referência e padrões vivem num router só, que simplesmente não é
registrado no público. Já `validate` está em `clips.py`, cujo resto é público —
partir o router em dois por causa de uma rota custaria mais que a guarda
explícita. Ela devolve 404, não 403: para quem não tem a feature, ela não existe.

### D82. A seção de aprendizado da home mora em `@/personal`

`LearningSection` e `SaveExampleButton` são exportados de `@/personal` e viram
`null` no stub. A home e o `ClipCard` renderizam `{X && <X />}` — sem `if` de
feature espalhado na tela, e sem o componente entrar no grafo do bundle público.

A busca das referências foi junto para dentro do `LearningSection`. Se ficasse na
home, a home continuaria chamando `listReferences` e a URL sobreviveria no bundle
público como código morto.

### D83. Um ciclo de importação real, e como ele apareceu

Ao exportar `LearningSection` de `@/personal`, criei um ciclo:
`index → LearningSection → ReferenceForm → @/personal`. O `ReferenceForm` lia
`PERSONAL_NICHES` em escopo de módulo, enquanto o index ainda inicializava —
`undefined`, e o spread estourava. **A home da versão pessoal passou a dar 500.**

Não apareceu no `tsc` nem nos 594 testes: só na verificação ao vivo, no log do
dev server.

**A correção:** as listas saíram para `personal/data.ts`, um módulo folha que não
importa componente nenhum. Quem é público importa de `@/personal` (que o stub
troca); quem já é pessoal importa da folha direto.

---

## Fatia 13 — Layouts por rubrica, e dois modos novos

### D84. Capa é só de podcast; facecam empilhada é só de gameplay

Não é preferência: os dois presumem coisas sobre o conteúdo. A **capa** é
escolhida pelo quadro mais expressivo de um ROSTO falando (`layout.py` usa
FaceMesh e boca aberta) — num gameplay ela pega uma tela de jogo, que não diz
nada. A **facecam empilhada** precisa de uma câmera separada do jogo; num
podcast o vídeo inteiro já é a câmera, e não há o que empilhar.

`crop` e `original` servem a qualquer rubrica porque não presumem nada:
recortar no centro e não recortar.

### D85. Antes de refatorar o render, congelei o que ele produz

O `cut_and_crop` tinha os componentes cobertos (capa, banner, faixa, marca) e
**nada cobrindo a montagem do filtergraph** — que é onde uma refatoração quebra
o vídeo de um jeito que só aparece assistindo.

Escrevi `tests/test_render_filtergraph.py` ANTES de tocar no código, capturando a
string exata que chega ao FFmpeg. Só então extraí o `_encode`, e o teste provou
que o filtro saiu idêntico.

O primeiro valor que escrevi estava errado — eu supus crop 9:16, e o real é
`1012:1080` (a área de vídeo é 1080x1152, não 9:16). O teste registra a
realidade, não o meu palpite.

### D86. "Crop vertical" é centralizado, sem face tracking

É o que "seco" quer dizer: o recorte é previsível, igual em todo clipe, e o
render não paga o MediaPipe. Quem quer o rosto acompanhado usa Capa + banner.

### D87. "Layout original" mantém a resolução da fonte

Um 4K sai 4K. É o modo para levar o corte a outro editor ou publicar onde o
vertical não é o formato — reamostrar contradiria o "sem alterar o
enquadramento" que ele promete. Legenda e limpeza de marcas continuam valendo:
elas não mexem no enquadramento.

### D88. `layout_mode` perdeu o default fixo

Ele era `"cover"`, resquício de quando podcast era a única suposição. Com a
regra nova isso passou a **recusar todo pedido de gameplay que não informasse o
layout** — quebrou 5 testes que já existiam, e teria quebrado qualquer cliente.

Agora é opcional e resolvido em ordem: o que veio no pedido → o padrão do perfil
→ o primeiro que a rubrica aceita. Mesma correção no `default_layout_mode` do
perfil.

### D89. A regra é espelhada e a paridade é verificada

`app/layouts.py` e `frontend/src/lib/layouts.ts`. Mesmo padrão do regex de URL
(D16): a cópia é o preço de decidir nos dois lados — a tela precisa saber o que
oferecer, o servidor precisa recusar o que não serve. O que dá para eliminar é a
chance de divergirem, e `test_frontend_e_backend_concordam` a elimina.

Um layout liberado só no frontend viraria um botão que o servidor recusa; só no
backend, uma opção que ninguém vê.

### D90. A recusa diz o que serve

`"O layout escolhido não serve à rubrica gameplay. Disponíveis: Facecam +
gameplay, Crop vertical, Layout original."` — erro que só nega deixa a pessoa
adivinhando.

---

## Fatia 14 — Fila de postagem sai do build público

### D91. A grade é do dono da instalação, não do usuário

12 horários por dia, fixos, cada um escolhendo o clipe que lidera um eixo da
rubrica, distribuídos entre as contas de quem administra. Num produto público
isso seria uma tabela de horários que o usuário não escolheu, apontando para
contas que não são dele.

Uma fila de postagem de verdade — horários configuráveis, saber onde publicar —
é outro produto. Não é o que existe hoje, e fingir que é seria pior que não ter.

Mesmo mecanismo das outras: o router de `/api/schedule/*` não é registrado, e o
`SchedulePanel` vem de `@/personal` (`null` no stub). Verificado que o painel
não está nos chunks que o navegador baixa.

### D92. HTML do servidor não prova nada numa página que monta no cliente

Ao verificar, procurei "Fila de postagem" no HTML de `/perfis/<id>` e achei 0 —
mas "Marca" e "Configuração atual" também deram 0. O `ProfileView` busca os
dados em `useEffect`, então o servidor entrega só `Carregando...`: a checagem
estava passando por acidente.

A prova é o BUNDLE: procurar nos chunks daquela rota. Ali "Fila de postagem" dá
0 e "Marca" dá 1 — que é o resultado que significa alguma coisa.

### D93. Um texto prometia o que o público não tem

O `SourceTypeSelector` dizia que a rubrica define "em qual conta o clipe entra no
cronograma de postagem". Com a fila fora do público, a frase virou promessa de
uma feature inexistente. Reescrita para o que vale nos dois builds: a rubrica
define os critérios da análise.

Achado varrendo o bundle atrás de vestígios — não estava no pedido.

### D94. A identidade padrão é a do ClipMint, não a de ninguém

As cores padrão da faixa e do banner eram as do dono da instalação (`#101014` /
`#9D9D9F`, banner `#ED2828`). Quem instalasse o ClipMint recebia a marca de
outra pessoa como ponto de partida.

Agora os padrões são os tokens do produto, os mesmos de `globals.css`: faixa
`#121714` sobre `#34D399`, banner `#34D399` sobre `#0B0F0D`. Vale nos dois
builds — os presets salvos em `storage/branding/` continuam ganhando, então a
instalação pessoal não muda de aparência.

### D95. `@suaconta`, e nunca o canal do vídeo de origem

`BAR_DEFAULT_NAME` era vazio, e no modo streamer o `cut_and_stack` caía em
`streamer_name=metadata.channel`: sem configurar nada, o clipe saía com a faixa
escrita **com o nome do canal de quem gravou o vídeo**, e não de quem publica.

O padrão passou a ser `@suaconta` e o parâmetro `streamer_name` foi removido da
função e da chamada no pipeline — não basta o padrão deixar de ser vazio, o
caminho para o canal de origem tinha que sumir. `test_branding_defaults.py`
guarda os dois lados da regra.

### D96. Os padrões de marca viviam em dois arquivos que não se falavam

`BarStyleSettings.tsx` e `BannerColorSettings.tsx` tinham suas próprias cópias
dos hexadecimais. Elas já estavam desatualizadas em relação ao backend, e o
efeito é pior que uma cor errada na tela: o preview desenha o que o FFmpeg vai
desenhar, então divergirem faz a tela **mentir sobre o vídeo**.

Centralizadas em `frontend/src/lib/branding.ts`, com paridade verificada por
`backend/tests/test_branding_defaults.py` — o mesmo remédio dado às regras de
layout (D91).

### D97. A marca d'água genérica é exemplo, e diz que é

`frontend/public/marca-clipmint.png`, gerada por `scripts/gerar_marca_clipmint.py`
(desenhada em código, para quem vier depois ver de onde saiu cada pixel).

Ela aparece apagada, tracejada e legendada no estado vazio do painel — e **não
entra no clipe**. Sem arquivo enviado, nenhuma marca é queimada, que é o
comportamento de sempre; mostrar o exemplo como se fosse a marca configurada
faria a tela prometer uma assinatura que o vídeo não tem.

### D98. Marca é configuração, e configuração fica em "editar perfil"

Os quatro painéis saíram do `ProfileView` e entraram no `ProfileForm`, reunidos
em `BrandSettings`. Ficam **fora do `<form>`**: cada painel salva sozinho, no
ato, e colocá-los dentro faria o botão "Salvar alterações" prometer o que ele
não faz.

Só na edição. Os presets são gravados numa pasta nomeada pelo id do perfil
(D42), e na criação esse id ainda não existe — a tela diz isso em vez de
oferecer campos que não teriam onde gravar.

### D99. O nome de uma feature pessoal vazava no bundle público

`lib/layouts.ts` entra no build público e trazia `streamer: ["gameplay", "siege"]`.
Nenhuma tela oferecia a rubrica, mas o nome viajava como texto no bundle de quem
não tem a feature — e a regra da separação é que ela não apareça.

A tabela partiu em duas: `BASE_LAYOUT_RUBRICS` (o que existe nos dois builds) e
`PERSONAL_LAYOUT_RUBRICS`, em `@/personal/data.ts`, vazia no stub. `layouts.ts`
funde as duas. O teste de paridade lê os dois arquivos e compara a soma com o
backend, então a regra completa continua verificada.

### D100. As rewrites são assadas no build, e o `BACKEND_PORT` ignorava o shell

A demo pública no 3001 estava proxyando para o **8001** — o backend PESSOAL, em
SQLite. Duas causas somadas:

1. `backendPort` lia só o `.env` da raiz, pelo mesmo motivo que `PUBLIC_BUILD`
   lia (D71): `loadRootEnv` só consulta o shell para chaves que já existem no
   arquivo. Corrigido para `process.env.BACKEND_PORT ?? rootEnv...`.
2. `rewrites()` é avaliado no **build** e gravado em `routes-manifest.json`.
   Passar a variável só no `next start` não muda nada — precisa rebuildar.

A demo agora tem `STORAGE_DIR=./storage-demo` também: com o storage
compartilhado, ela lia os presets de marca do dono e mostrava a logo dele.

**Adendo (27/08/2026).** Essa segunda metade nunca chegou ao repositório: o
`.gitignore` já esperava a pasta, mas o `_serve-public-backend` do Makefile
continuava sem a variável, e o `make serve-public` seguia dividindo o
`./storage` com o `make dev`. Corrigido — `PUBLIC_STORAGE_DIR` fica declarado
uma vez, ao lado da porta deslocada, pela mesma razão: as duas versões têm que
conviver sem enxergar os arquivos uma da outra.


### D101. `SQLITE_URL` vence `DATABASE_URL`, e por isso o público tem variável própria

Ao apontar o build público para o Postgres, definir `DATABASE_URL` não bastava:
`config.db_url` devolve `sqlite_url or database_url`, e o `.env` tinha
`SQLITE_URL` desde sempre. A precedência é intencional e tem teste
(`test_sqlite_url_antigo_continua_valendo`) — um `.env` que já funcionava não
pode trocar de banco porque uma variável nova apareceu. O que estava errado eram
os comentários: `config.py` afirmava o oposto do código, e a mensagem do guard
de startup culpava a `DATABASE_URL` mesmo quando quem mandava era a `SQLITE_URL`.

Corrigidos os três textos (config, `.env.example`, mensagem do guard, que agora
nomeia a variável em vigor). E como o `.env` é **um só** para as duas versões,
apontar `DATABASE_URL` para o Postgres levaria junto o `make dev` pessoal, que
tem o histórico no `clipmint.db`: o público lê `PUBLIC_DATABASE_URL`, que o
Makefile passa como `DATABASE_URL` só para o processo público — zerando o
`SQLITE_URL` dele, senão o nome antigo ganharia. Mesma lógica das portas
deslocadas: as duas versões convivem na mesma máquina.

### D102. Crédito é inteiro, e o saldo é cache travado por linha

1 crédito = 1 minuto de vídeo, `ceil`, em `INTEGER`. Crédito fracionário em
ponto flutuante vira saldo de 29.999999 e discussão com o usuário.

`credit_ledger` é append-only e é a fonte da verdade; `users.credit_balance` é
cache atualizado na mesma transação. O cache não existe por performance: é a
LINHA que é travada com `SELECT ... FOR UPDATE` antes de cada lançamento, e é
esse lock que impede dois jobs simultâneos de gastarem o mesmo saldo. Derivar
por `SUM()` precisaria do mesmo lock de qualquer forma.

Detalhe que quase passou: o `FOR UPDATE` precisa vir com `populate_existing`.
Sem ele, quando o usuário já está na sessão (o caso comum — veio da dependência
de autenticação), o SELECT trava a linha no banco mas devolve o objeto em
memória com o saldo ANTIGO. O lock ficaria de enfeite, e o erro só apareceria
sob concorrência, cobrando errado.

### D103. As garantias de "uma vez só" moram no banco, não no código

Três índices únicos parciais em `credit_ledger`: um pagamento credita uma vez
(`ref_payment_id` com `tipo='topup'`), um job segura uma vez e cobra uma vez
(`ref_usage_id` com `tipo='hold'` e `'debito'`). Mais `payments.gateway_payment_id`
UNIQUE.

O webhook do Mercado Pago reenvia notificação, e duas notificações simultâneas
do mesmo pagamento passariam por qualquer verificação feita em Python — nenhuma
passa por um índice único. O caso do job não é hipotético: este projeto já
retoma job à mão depois de reinício (ver `project_job_recovery`), e retomar não
pode cobrar de novo pelo mesmo trabalho.

### D104. O primeiro teste de concorrência passava com o lock desligado

A primeira versão disparava 8 requisições com `asyncio.gather` e afirmava que
só uma passava. Passava mesmo — e continuava passando com o `with_for_update()`
REMOVIDO: as tarefas serializavam sozinhas e a janela perigosa nunca chegava a
abrir. Um teste de concorrência que passa com a proteção desligada é decoração.

O teste que ficou força o intercalamento à mão: a sessão A lança e não commita,
a sessão B tenta e **tem que ficar bloqueada** (é o `wait_for` estourando que se
afirma), A commita, B acorda e vê o saldo já debitado. Sem o lock, o passo do
meio não bloqueia e o teste falha — verificado removendo o lock de propósito.

A lição vale além daqui: teste de proteção só conta depois de vê-lo falhar com
a proteção fora.

### D105. Assinatura vai no cartão; Pix fica no avulso

A API de assinaturas do Mercado Pago tem dois modelos: *com pagamentos
autorizados*, em que o MP cobra sozinho a cada ciclo, e *com pagamentos
pendentes*, em que não há meio de pagamento definido e cada cobrança nasce
`pending` esperando o usuário pagar. A tabela de meios da documentação lista Pix
entre os aceitos — mas Pix cai no segundo modelo: todo mês o usuário recebe uma
cobrança e paga à mão. Isso é um carnê, não uma assinatura.

Cobrança automática sem ação por ciclo depende de tokenização de cartão. Sobre o
**Pix Automático** (o débito recorrente do BCB): o MP o divulga em posts de
blog institucional, mas não foi possível confirmar caminho de API na
documentação técnica — as páginas de referência são renderizadas por JS e não
respondem a fetch. Blog de marketing não é contrato de API, então isso fica como
NÃO VERIFICADO.

Decisão: Pix para o avulso, cartão para a assinatura, e a camada de assinatura
falando com uma interface de gateway — nunca com o MP direto. Quando o Pix
Automático for confirmado, ele entra como outra implementação da interface, sem
tocar no ledger nem nas telas.

---

### D106. Pix contra a Orders API, e o status falha fechado

A cobrança Pix vai contra `POST /v1/orders` (Orders API), que é o que a
documentação atual do Pix descreve. A API clássica (`/v1/payments`) continua
existindo e é o que a maioria das integrações antigas usa, mas as páginas de
referência dela são renderizadas por JS e não foi possível conferir o formato —
e integração de pagamento não se escreve de memória.

O que ficou **por confirmar contra o sandbox**: o vocabulário completo de
status. A documentação enumera `action_required`, `processing` e o detalhe
`waiting_transfer`, mas não fecha a lista dos estados finais. Por isso o
mapeamento é uma **allowlist** (`_STATUS_PAGOS`), nunca denylist: status
desconhecido NÃO credita, fica no log com o valor original, e o pagamento
continua pendente. Errar para o lado de não creditar é recuperável; errar para o
lado de creditar sem receber, não.

E a regra que não se negocia: **o corpo da notificação não é fonte de verdade**.
Ele diz "olhe o recurso X"; quem diz se foi pago é uma consulta autenticada ao
gateway. Assim, mesmo que a assinatura um dia seja contornada, ninguém credita
saldo postando JSON na nossa API.

O `GET /api/billing/payments/{id}` da tela faz essa mesma sincronização, e não
só lê o banco: em desenvolvimento o webhook NUNCA chega, porque o Mercado Pago
não alcança um localhost. Sem isso, todo teste de ponta a ponta ficaria preso em
"aguardando pagamento" com o Pix já pago.

### D107. O webhook morria no middleware do Next, com 401

A guarda do build público devolve 401 para todo `/api/*` sem cookie de sessão. O
Mercado Pago não tem cookie e nunca terá: a notificação de pagamento morreria
ali, sem nunca chegar ao backend — o usuário pagaria o Pix e o saldo não
entraria. Só apareceria em produção, porque em desenvolvimento o webhook não
chega de qualquer forma (ver D106).

`/api/billing/webhook` agora passa nas duas cercas — a do Next e a de perímetro
do `main.py` — e isso não abre nada: quem autentica ali é a assinatura HMAC,
que é obrigatória (sem `MERCADOPAGO_WEBHOOK_SECRET` o endpoint recusa tudo, em
vez de aceitar tudo).

Conferido no servidor rodando, e os dois 401 se distinguem pelo corpo:
`/api/billing/webhook` responde `{"detail":"Assinatura inválida."}` — que é o
backend — enquanto `/api/billing/topup` responde `{"detail":"Faça login para
continuar"}`, que é o middleware.

### D108. Creditar uma vez é a transição de status, não um `if`

Quem arbitra qual processo credita é um UPDATE condicional:
`UPDATE payments SET status='paid' WHERE id = :id AND status <> 'paid'`. Só um
consegue rowcount 1, e só esse lança no ledger. A condição precisa estar DENTRO
do UPDATE: um `if pagamento.status == 'paid'` em Python lê um valor que já pode
estar velho, enquanto o `WHERE` é avaliado pelo banco com a linha travada.

Verificado trocando um pelo outro (mesmo método da D104, e de novo a versão com
`asyncio.gather` passava com a trava desligada — o teste que vale força o
intercalamento à mão). Com o `if` em Python, o teste falha — e falha no índice
único `uq_credit_ledger_topup_por_pagamento`, com `balance_after: 600` para uma
compra de 300. A segunda barreira pegou o que a primeira deixou passar, que é
exatamente para isso que ela existe (D103).

---

### D109. Sem saldo o job não nasce, e a reserva sai na hora

A reserva de crédito vai na MESMA transação que cria o job. Sem saldo,
`segurar` levanta 402 e a transação inteira volta atrás: não fica job órfão que
ninguém vai processar e que ainda assim aparece na lista do usuário como
trabalho pedido. O 402 (e não 403) é o que a interface usa para mandar a pessoa
à recarga — falta saldo, não falta permissão.

O `hold` sai do saldo imediatamente, e é isso que impede disparar dez jobs com
crédito para um: o segundo pedido já não encontra saldo. É a mesma ideia do
`FOR UPDATE` da D102, uma camada acima.

**A ordem entre `release` e `debito` na reconciliação não é estética.** Com saldo
B e reserva E, o saldo durante o job é `B - E`. Debitar antes de devolver
tentaria `B - E - R`, negativo sempre que a reserva consumiu quase tudo — e o
lançamento seria RECUSADO por saldo insuficiente, num job que já rodou e cujo
dinheiro já foi gasto. Devolver primeiro leva a `B`, e o débito cai em cima.

Verificado direto: com saldo 5 e reserva 5, debitar primeiro devolve
`Saldo insuficiente: são necessários 5 créditos e você tem 0`. Cinco testes
falham quando a ordem é invertida.

E quando o vídeo era MAIOR do que a consulta de metadados disse, cobra-se o
reservado, não o real. O erro foi da nossa medição, e quem viu "~E créditos" na
tela foi o usuário: a diferença vira log para ser investigada, não cobrança
surpresa.

### D110. Todo caminho terminal devolve a reserva — são quatro

Um caminho esquecido deixa crédito preso para sempre, então vale listar:

| Saída | O que acontece |
|---|---|
| `done` | devolve a reserva e cobra os minutos reais |
| `error` | devolve a reserva, não cobra nada |
| Job excluído | devolve **antes** de apagar: quem devolveria era o pipeline, e ele não vai mais rodar |
| Restart do servidor | `reconcile_interrupted_jobs` devolve — senão o usuário perderia saldo por um reinício |

`JobAlreadyRunning` de propósito NÃO devolve: lá o job tem outro dono vivo, e
mexer na conta dele seria o mesmo erro que mexer no status dele.

**A contabilidade nunca derruba o pipeline.** `reconciliar_job` engole qualquer
exceção e registra. O status do job é o que o usuário vê e já foi decidido
quando ela roda: saldo por conciliar é recuperável, job marcado como erro por
causa da contabilidade não é.

**Job que falhou não é cobrado** (`COBRAR_JOB_QUE_FALHOU = False`). O usuário não
recebeu clip nenhum, e cobrar por trabalho não entregue é o caminho curto para
pedido de estorno. O que se perde é a transcrição já paga de um job que quebrou
depois dela — custo real, mas nosso, e do tamanho de um bug nosso. É uma
constante só, porque é decisão de negócio.

### D111. O extrato sobrevive ao job apagado, e a cota de janela saiu de cena

A 0006 criou `credit_ledger.ref_usage_id` com chave estrangeira comum, e com ela
o DELETE de um job seria RECUSADO enquanto houvesse lançamento apontando para
ele — o extrato passaria a mandar no que o usuário pode fazer com o trabalho
dele. Apagar o lançamento junto também não serve: é registro financeiro. A 0007
troca para `ON DELETE SET NULL`, e o elo não se perde porque `descricao` guarda
o id do job em texto.

**A 0007 quebrou a cadeia inteira no SQLite na primeira versão.** Ela removia a
FK pelo nome `credit_ledger_ref_usage_id_fkey` — que é um nome que o *Postgres*
gera sozinho e que no SQLite não existe, porque lá a FK nasceu sem nome. Como
o SQLite só aplica chave estrangeira com `PRAGMA foreign_keys` ligado, e este
projeto nunca liga, não havia nada a corrigir lá: a alteração agora acontece só
no Postgres, e o índice novo nos dois.

Sobre a **cota por janela**: ela era a trava de custo enquanto o uso era grátis.
Com saldo, quem trava o custo é o saldo, e manter as duas significaria recusar
trabalho de quem PAGOU por ele — pior que não ter limite. Os padrões do público
(`PUBLIC_QUOTA_MAX_*`) saem de cena; `QUOTA_MAX_VIDEOS`/`QUOTA_MAX_MINUTES`
preenchidos à mão continuam valendo, como alavanca de emergência.

O que NÃO saiu: o teto de duração por vídeo e a recusa de transmissão ao vivo.
Essas nunca foram cobrança — são sanidade. A live não tem fim previsto e o vídeo
de 8 horas estoura o prompt de análise.

---

### D112. A tela nunca calcula preço nem custo

O catálogo (`/api/billing/catalog`) chega com o preço de cada pacote JÁ
RESOLVIDO, pela mesma função que a criação da cobrança usa
(`billing.preco_do_pacote`). E a estimativa (`/api/billing/estimate`) usa a
mesma função que reserva o crédito (`usage.custo_em_creditos`).

Seria mais simples mandar `credito_avulso_brl` e deixar o frontend multiplicar.
Só que aí o primeiro pacote com desconto faria a tela e a cobrança discordarem —
e quem discorda por último é a fatura. Mesma razão de `quota.usage()` já
compartilhar a contagem com `check_quota`: uma segunda fórmula para mostrar na
tela vira uma tela que discorda do que o servidor faz.

A estimativa passa pelas MESMAS guardas da criação (live, teto de duração) e
levanta os mesmos 422. Uma tela que promete um vídeo que o servidor vai recusar
em seguida é pior que nenhuma tela.

### D113. O extrato mostra `hold` e `release`, não um resumo

A tentação é esconder reserva e devolução porque "se anulam" e poluem. É o
contrário: é justamente vê-las que explica por que o saldo caiu 120 quando o
job começou e voltou a subir quando ele terminou. Escondidas, a mesma sequência
parece cobrança dupla — e o suporte que isso gera custa mais que a linha extra
na tabela.

Elas aparecem em tom mais apagado que recarga e cobrança: presentes para quem
procura, discretas para quem só quer saber quanto gastou.

### D114. O saldo mora na navbar, e é atualizado por evento

Num produto pago por consumo a pergunta "quanto me resta?" vem antes de cada
ação. Obrigar a abrir outra tela para responder é o que faz a pessoa parar de
gerar.

A sincronização entre navbar e telas é um **evento de janela**
(`clipmint:saldo`), não um provider nem uma biblioteca de estado. O que precisa
acontecer é "gastei/recarreguei, atualize o número no topo": um evento resolve
sem enfiar um provider no layout inteiro e sem uma dependência nova. Quem muda o
saldo chama `avisarSaldoMudou()`; quem mostra, escuta.

Dispara em três pontos: ao criar o job (a reserva já saiu), quando o job chega a
status terminal (a conta fechou) e quando o Pix é confirmado.

### D115. O acompanhamento do Pix é por polling, não por espera do webhook

A tela de recarga consulta `/api/billing/payments/{id}` de 3 em 3 segundos, e
esse endpoint sincroniza com o gateway (D106). Esperar o webhook chegar seria
mais elegante e não funcionaria: em desenvolvimento o Mercado Pago não alcança
um localhost, e em produção uma notificação pode atrasar ou se perder. Com
polling a tela se resolve sozinha nos dois casos, e o webhook vira otimização em
vez de requisito.

Assinatura aparece com preço real e etiqueta "Em breve" — a Fatia 5 ainda não
existe. Um botão que não funciona seria pior: o preço já é a informação que a
pessoa precisa para decidir entre esperar e comprar avulso.

---

### D116. A assinatura é criada SEM `card_token_id`

O `preapproval` do Mercado Pago aceita os dois caminhos. Com `card_token_id`, o
cartão é digitado na NOSSA página e tokenizado por nós — escopo de PCI que um
produto recém-lançado, com recebedor em CPF, não tem por que assumir. Sem ele a
assinatura nasce `pending`, o gateway devolve um `init_point`, e o cartão é
digitado na página deles. Nunca vemos número de cartão.

O preço vai em `auto_recurring.transaction_amount`, resolvido pelo servidor a
partir do plano da `billing_config`, e é CONGELADO em `subscriptions.valor_brl` e
`creditos_mes`: subir o preço do Pro amanhã não reescreve o que já foi vendido.

Isso criou um estado que a 0006 não previa. Assinatura esperando autorização não
é `active`, nem `canceled`, nem `paused` — a 0008 acrescenta `pending` ao CHECK e
guarda o `init_point`, porque quem fecha a aba no meio precisa poder voltar; sem
o link, clicar de novo criaria uma segunda assinatura no gateway.

Detalhe da 0008 que a 0007 não teve: **o CHECK é aplicado pelos dois dialetos**
(diferente da chave estrangeira, que o SQLite ignora sem `PRAGMA foreign_keys`).
A alteração acontece nos dois, e no SQLite isso significa recriar a tabela.
Conferido que o CHECK sobrevive à recriação: `pending` passa, `inventado` é
recusado com `CHECK constraint failed: ck_subscriptions_status`.

### D117. O ciclo credita pelo MESMO caminho da recarga avulsa

Cada cobrança mensal vira uma linha em `payments` (`tipo='assinatura'`,
`subscription_id` preenchido) e o crédito é lançado por
`payments._marcar_pago_e_creditar`. Não existe um segundo mecanismo de crédito
para assinatura, de propósito: a idempotência que a Fatia 2 construiu
(`gateway_payment_id` único + transição condicional de status) vale igual para o
ciclo, e um caminho paralelo teria que reconstruir tudo isso — e erraria.

Consequência boa e não óbvia: a idempotência é **por cobrança, não por
assinatura**. Dois meses creditam duas vezes; a mesma notificação três vezes
credita uma. Ambos testados.

E se a notificação do ciclo chegar ANTES da autorização, o pagamento aprovado é
prova de que a assinatura está ativa — ela é promovida a `active` ali mesmo, em
vez de ficar `pending` com dinheiro já recebido.

### D118. Cancelar fala com o gateway primeiro

Marcar como cancelada aqui e falhar lá deixaria a pessoa achando que parou de
pagar enquanto o cartão continua sendo debitado — o erro mais caro possível
nesta direção. Então: cancela no gateway, e só depois marca aqui. Se o gateway
recusa, a resposta é 502 com a frase explícita "sua assinatura NÃO foi
cancelada", e a linha continua viva.

Os créditos já concedidos ficam: o mês foi pago.

O roteamento do webhook também mudou. Ele agora despacha por tipo
(`subscription_authorized_payment`, `subscription_preapproval`, `payment`) e,
quando o tipo não é reconhecido, procura no NOSSO banco em vez de chutar um
endpoint do gateway. A diferença importa: um `GET /authorized_payments/<id>` com
um id que não é disso devolveria 404, viraria 503 daqui, e o Mercado Pago
reenviaria para sempre uma notificação que nunca conseguiríamos tratar.

---

### D119. `usage_events` é o outro lado do `credit_ledger`

Parecem redundantes e não são: o ledger registra o que o **usuário pagou**, em
créditos; `usage_events` registra o que **nós pagamos**, em dólar e real. É o
cruzamento dos dois que diz se um cliente dá lucro — nenhum dos dois sozinho diz.

**Um registro por VÍDEO, não por clipe.** A fatura da AssemblyAI e da Anthropic
é por minuto de vídeo: um job que gera oito clipes custa o mesmo que um que gera
dois. Contar por clipe inflaria o custo por um número sem relação nenhuma com a
conta que chega.

`credits_charged` é o campo que fecha o par com a receita, e existe por causa da
decisão de não cobrar job que falha (D110): esses eventos ficam com custo maior
que zero e `credits_charged = 0`, e é exatamente essa combinação que o painel
soma para mostrar quanto está sendo perdido ali. `status` separa `failed` de
`deleted` porque a causa é diferente — um é bug nosso, o outro é o usuário
desistindo — e a resposta a cada um também.

Índice único parcial em `job_id`: um vídeo, um evento. Mesma disciplina do
ledger, e pela mesma razão — os quatro caminhos terminais da D110 podem
disparar mais de uma vez, e custo contado em dobro é pior que custo não contado.

### D120. As tarifas de LLM ficam num mapa por modelo

O prompt do monitor pedia `opus_input_usd_per_mtok` e `opus_output_usd_per_mtok`,
duas colunas fixas. Viraram um mapa `{modelo: {input, output}}`, e o evento grava
QUAL modelo rodou.

O motivo apareceu antes de escrever qualquer código: o prompt dizia que a análise
usa Opus 4.8, e o `config.py` roda **`claude-sonnet-4-6`**. As tarifas não são as
mesmas — Opus 4.8 é $5/$25 por MTok e Sonnet 4.6 é $3/$15 — então os defaults do
prompt, aplicados no tráfego real, superestimariam o custo de análise em ~67%.
Um painel de lucro que erra o custo para cima faz recusar cliente que dá lucro.

Com colunas fixas, trocar de modelo exigiria migração e o evento antigo passaria
a ser lido com a tarifa do modelo novo. Com o mapa, a troca é uma linha na
configuração e o histórico continua congelado no `rate_snapshot`. Os dois modelos
já estão semeados, então a decisão de trocar não depende de deploy.

Decisão do dono em 27/08/2026: **fica no Sonnet**.

### D121. O que o monitor não reconhece é MARCADO, não zerado

Duas situações passam pelo cálculo sem tarifa exata: modelo sem preço cadastrado
e provedor de transcrição diferente do cotado. Nos dois casos a saída fácil seria
zerar.

Zerar mente para baixo, e custo subestimado é justamente o erro que faz aceitar
cliente deficitário — o oposto do que este painel existe para evitar. Então:
modelo sem tarifa entra com análise 0 **e** `analysis_rate_missing: true` no
snapshot; provedor diferente usa a tarifa que existe **e** marca
`transcription_rate_mismatch: true`. O painel pode mostrar a lacuna; o silêncio
não daria essa chance.

Pela mesma lógica, o arredondamento é de seis casas em USD: a tarifa de
transcrição é 0,0035 por minuto, e arredondar a centavo a faria desaparecer.

---

### D122. Os tokens só existem uma vez, e o custo parcial precisa de prova

A API devolve `usage` na resposta da análise e esse número **não volta depois**.
O `analyzer.py` já o lia — e jogava num log. Agora ele grava, no mesmo ponto,
antes que a informação se perca; sem isso o custo de análise viraria estimativa
por contagem de caracteres, que é justamente o que este monitor não quer ser.

Daí o evento ter **dois momentos e uma linha só**: `registrar_analise` escreve os
tokens quando eles existem, `fechar` completa quando já se sabe como o job
terminou e quanto o usuário pagou. Os dois escrevem na mesma linha, pelo
`job_id` (índice único). Se o processo morrer entre um e outro, sobra um evento
com tokens e sem fechamento — que é a verdade ("pagamos a análise e não sabemos
como terminou"), e não um silêncio.

**O custo parcial é decidido por evidência, não por status.** Um job pode morrer
no download (não custou nada), depois da transcrição (custou os minutos) ou
depois da análise (custou os dois):

  - transcrição paga = **existe linha em `transcripts`** para este job;
  - análise paga = os tokens foram registrados;
  - storage = só se houve transcrição (implica mídia baixada).

`jobs.duration_seconds` **não serve de prova** e essa é a armadilha: ele é
preenchido na CRIAÇÃO do job, pela consulta de metadados, e existe cheio mesmo
num job que morreu antes de baixar um byte. Usá-lo como sinal cobraria
transcrição de vídeo que nunca foi transcrito.

**`credits_charged` vem do ledger, não de um parâmetro.** É por isso que `fechar`
roda DEPOIS da reconciliação: antes dela o débito ainda não existe e todo job
pareceria prejuízo.

E, como o `reconciliar_job` da D110, tudo aqui **engole exceção**: vídeo pronto
não pode virar job com erro por causa da contabilidade. As funções vêm em par —
núcleo que recebe sessão, invólucro que abre a sua — porque `AsyncSessionLocal`
aponta para o banco real e um teste que chamasse o invólucro estaria medindo
outro banco. Mesma separação de `usage.reconciliar` / `reconciliar_job`.

---

### D123. A fronteira do mês é America/São_Paulo, e isso não é cosmético

As colunas de data são `timestamptz` em UTC. "Mês corrente" para quem toca o
negócio é o mês em São Paulo — é o que bate com o extrato do contador. Em UTC,
**as três últimas horas de todo dia 31 caem no mês seguinte**: um pagamento às
23h do dia 31/07 viraria receita de agosto.

A borda é calculada no fuso local e CONVERTIDA para UTC antes de ir ao banco: a
comparação continua sendo entre instantes, que é o que um índice sabe fazer
rápido. Verificado trocando o fuso por UTC de propósito — o teste da virada
falha, que é o que se quer de um teste de fronteira.

O agrupamento da série diária é feito em Python, e não em SQL, pelo mesmo
motivo invertido: o dia depende do fuso, e `AT TIME ZONE` não existe no SQLite
dos testes. Uma consulta que só roda em produção é a pior forma de descobrir que
ela está errada. As consultas trazem duas colunas por linha — instante e valor —
e na escala deste produto isso é um mês de eventos. Se passar de dezenas de
milhares, o caminho é agregação materializada, não um `GROUP BY` mais esperto.

### D124. Estimativa entra marcada, e o mês corrente vem com o anterior

Duas coisas no painel não são medição, e as duas voltam com aviso: a **taxa do
gateway** enquanto o pagamento não liquidou (o Mercado Pago só a informa depois,
e até lá vale o percentual da configuração) e o **imposto**, que é placeholder
até o contador confirmar. Um número estimado sem etiqueta vira fato na cabeça de
quem lê — e este painel existe para decidir preço e rate limit.

`overview` devolve o mês pedido **e o anterior**: R$ 400 de lucro é ótimo depois
de R$ 100 e péssimo depois de R$ 900, e um número sozinho não distingue os dois.

O custo fixo entra INTEIRO mesmo em mês corrente — o servidor já foi pago —, e a
série diária mostra lucro só de receita menos custo variável: ratear custo fixo
e imposto por dia desenharia uma curva que não existe.

Churn é sobre a base do INÍCIO do mês, reconstruída como
`ativos_hoje − novos + cancelados`. Dividir pelos ativos de hoje subestimaria o
churn justamente nos meses ruins, que são os que interessam.

### D125. A porta do painel é no backend, e o 403 deixou de falar de branding

`/admin` fica atrás de `require_owner` no **servidor**. Esconder na interface não
é proteção: quem descobrir a URL tem que levar 403 do backend. O router também só
é registrado no build público — mas isso é conteúdo (lá não há receita para
monitorar), não segurança.

Reusar `require_owner` trouxe um efeito colateral pequeno e real: ele nasceu para
os presets de marca, e quem tentava abrir o painel recebia *"Os presets de marca
são compartilhados nesta instalação..."* — um texto que não explica nada de onde
a pessoa está. A mensagem do 403 virou genérica; o porquê específico do branding
continua no docstring, que é onde quem lê o código procura.

---

### D126. Verde e vermelho, medidos, dão ΔE 6,5 em deuteranopia

O gráfico do painel ia codificar lucro por cor: mint para positivo, danger para
negativo. Rodei o validador de paleta contra a superfície escura antes de
escrever o SVG, e ele reprovou:

```
[WARN] CVD separation  worst adjacent #f87171↔#34d399 ΔE 6.5 (deutan)
```

É o clássico vermelho/verde, e é o tipo de CVD mais comum. Quem enxerga assim
não distinguiria lucro de prejuízo pelo matiz — num painel cuja pergunta é
exatamente essa.

O sinal passou a ser codificado **três vezes**: pela DIREÇÃO da barra em relação
à linha do zero, pelo `+`/`−` escrito no valor, e só então pela cor. Mesma regra
na variação dos indicadores (▲/▼ mais o sinal) e na tabela por usuário (tarja na
lateral mais a etiqueta "prejuízo", não a cor da linha sozinha).

A lição é a mesma da D104, noutro domínio: **não avalie a olho o que dá para
computar.** A paleta do produto parecia óbvia e estava errada para uma parte dos
leitores.

### D127. Barras de lucro, e não três linhas

O pedido era "receita, custo e lucro por dia". Três linhas fariam o leitor
conferir a subtração no olho — lucro É receita menos custo, não uma terceira
medida independente. E dinheiro por dia é DISCRETO: um dia sem pagamento é um
zero de verdade, não um ponto de uma curva contínua; barra representa isso, linha
sugeriria um fluxo que não existe.

Ficou: barras de lucro (a pergunta que traz alguém à tela), com receita e custo
no hover **e** numa tabela sob o gráfico. A tabela não é enfeite de
acessibilidade — é o que garante que nenhum número viva só no `:hover`, o que
quebraria em impressão, leitor de tela e toque.

A ordem da página segue a ordem da pergunta: resultado do mês, desenho dele no
tempo, quem está dando prejuízo, tarifas que produziram tudo. E os **avisos de
estimativa ficam entre os números e o gráfico**, não num rodapé: quem lê "lucro
de R$ 112" precisa saber ali que parte daquilo é estimada.

---

### D128. Registrar receita e entregar crédito são coisas diferentes

O lançamento manual do painel tem uma caixa "entregar créditos", e ela nasce
**desmarcada**. Um Pix recebido na chave quer as duas coisas; uma correção de
contabilidade quer só a primeira. Conceder por padrão daria crédito de graça
toda vez que o dono só quisesse acertar o extrato — e crédito concedido por
engano não volta sem deixar a conta de alguém negativa.

Quando o crédito é concedido, ele passa pelo MESMO caminho do gateway
(`payments._marcar_pago_e_creditar`): a idempotência da Fatia 2 vale igual, e um
segundo mecanismo de crédito erraria onde aquele já acerta.

**A idempotência do lançamento manual é a referência do Pix.** O
`gateway_payment_id` recebe `manual:<referência>` e é único, então o mesmo E2E
lançado duas vezes é recusado pelo banco — que é o erro provável aqui: conferir o
extrato, lançar, e lançar de novo na semana seguinte. Sem referência não há
proteção, e por isso o campo é PEDIDO com o motivo escrito na tela, não
obrigatório: quem tem o comprovante ganha a garantia, quem não tem consegue
lançar assim mesmo.

Tudo isso escreve nas MESMAS tabelas do webhook. Uma tabela paralela para o que
é manual daria dois totais que discordariam no primeiro fechamento de mês; o que
distingue é a coluna `gateway`.

### D129. Estorno tira do mês e não mexe no saldo

Marcar um pagamento como `refunded` ou `chargeback` limpa o `paid_at`, e com isso
ele sai da receita do mês — que é o efeito desejado quando o dinheiro volta.

O que NÃO acontece é retirar os créditos. Quem já processou vídeo com aquele
saldo ficaria negativo, e o extrato passaria a mostrar um débito que ninguém
pediu. Se for para cobrar de volta, isso é um `ajuste` explícito no ledger — o
único tipo que pode deixar a conta negativa (D102), justamente porque é uma
decisão consciente de alguém.

E o cancelamento de assinatura do painel só aceita as **manuais**. Encerrar uma
do gateway por aqui a marcaria como encerrada sem avisar o Mercado Pago, e o
cartão continuaria sendo debitado — o erro mais caro possível nessa direção
(D118). As do gateway saem pelo fluxo do usuário, que fala com o gateway antes.

---

### D130. O vocabulário de status da Orders API, fechado

A D106 registrou como NÃO VERIFICADO qual status o Mercado Pago devolve num
pagamento aprovado. Ficou verificado em 27/08/2026, e por dois caminhos que se
confirmam:

  - **contra a API de verdade** (credencial de sandbox): `POST /v1/orders` com o
    payload que implementei devolveu **201** com QR e copia-e-cola válidos, e
    status `action_required` / `waiting_transfer`. A Orders API é o caminho
    certo e o formato do payload está correto;
  - **contra a documentação**, a lista completa dos nove valores possíveis:
    `created`, `processed`, `processing`, `action_required`, `canceled`,
    `charged_back`, `expired`, `failed`, `refunded`. Pago é **`processed`** com
    `status_detail: accredited`.

`processed` já estava na allowlist — o caminho do dinheiro estava certo desde o
início. Mas a lista completa expôs dois valores sem mapeamento: **`expired` e
`failed`**. Eles caíam em "status desconhecido", e a consequência não era perder
dinheiro (falha fechado, não credita) e sim uma tela dizendo "aguardando
pagamento" para sempre num QR que já não pode ser pago.

A 0011 acrescenta `expired` a `payments.status`. Os dois valores do gateway
colapsam nesse único: a CAUSA difere, a resposta não — para o usuário, "gere
outra cobrança"; para o monitor, "isto nunca foi receita".

**O que ainda não foi exercido:** um Pix efetivamente PAGO. O painel web do
Mercado Pago não paga copia-e-cola ("abra o app no celular"), e conta de teste
não entra no app de produção. O status de pagamento está confirmado pela
documentação, não por uma transação — e o primeiro pagamento real fecha isso
sozinho, sem risco, porque `processed` já é aceito.

Também confirmado na prática: a validação HMAC do webhook, testada com o segredo
real da aplicação — assinatura correta devolve 200, assinatura errada devolve
401. Essa parte eu tinha escrito só a partir da documentação.

---

### D131. Quem decide se o job já foi cobrado é o débito, nunca a devolução

A conta de um job tem três lançamentos: `hold` ao criar, `release` ao terminar,
`debito` quando deu certo. A reconciliação saía cedo ao encontrar um `release`,
tratando-o como "este job já está resolvido".

Não está. **Um job que falha devolve a reserva e pode ser retomado depois** — e
a retomada entrega os clips. Com o `release` como sentinela, essa entrega não
cobrava nada: bastava falhar uma vez antes de dar certo para levar o vídeo de
graça. E falhar é comum (rede, chave de API vencida, restart no meio de um
render), com um botão "Retomar de onde parou" bem visível ao lado.

O sinal certo é o `debito`. Enquanto ele não existe, uma conclusão
bem-sucedida cobra — tenha havido devolução antes ou não. A devolução continua
acontecendo uma vez só, e o "uma vez" de cada um dos três segue garantido pelos
índices únicos parciais do banco (0006/0007), não por `if` em Python.

Duas consequências que precisaram de decisão própria:

**A porta fica no `retry`, não na cobrança.** Retomar um job cuja reserva já foi
devolvida é uma compra, então o endpoint confere saldo e devolve 402 — o mesmo
que a criação de job, e a tela manda para a recarga. Recusar só na hora de
cobrar significaria renderizar o vídeo inteiro para descobrir na última linha
que não há como cobrá-lo. Três retomadas continuam de graça, e as três são
legítimas: job sem reserva (versão pessoal, ou anterior à cobrança), job já
cobrado (re-renderizar um clip que falhou não é uma segunda compra), e job com
a reserva ainda de pé (já está pago adiantado — sem essa exceção, um job morto
no restart cujo `hold` consumiu todo o saldo ficaria impossível de retomar,
porque o crédito que faltaria é o que ele mesmo segurou).

**A retomada pode deixar a conta negativa.** Entre a falha e o fim da retomada
o crédito devolvido pode ter ido para outro vídeo. O trabalho foi entregue: a
conta fica devendo e quem espera é o job seguinte, que não nasce sem saldo. É a
única saída que não dá o clip de graça, e é o segundo caso em que `debito` usa
`permitir_negativo` (o primeiro é o `ajuste` de admin, D102). No caminho normal
é inalcançável — ali o custo real nunca passa da reserva, que ainda está presa.

A D110 (job que falha devolve tudo e não é cobrado) continua valendo sem
ressalva. O que muda é só isto: **falhar não é o fim da história do job**, e
"devolvi" nunca quis dizer "acabou".

---

## Adiado, com destino definido

| Item | Fatia | Por quê ali |
|---|---|---|
| Teto de duração do vídeo de origem | 7 | Trava de custo; pertence ao módulo de proteção junto do rate limit. **Medido:** a transcrição inteira entra no prompt sem truncagem — 12h ≈ 252k tokens, acima dos 200k do Sonnet. O teto aprovado (120 min ≈ 43k tokens) tem folga larga. |
| Vídeo sem fala paga a análise | 7 | Mesma trava de custo. Confirmado: prompt com 0 palavras é montado sem erro e vai para a API. Quando entrar, grava o motivo em `result_note` (D13). |
| Limite de concorrência de jobs | 7 | Nenhum `Semaphore` no projeto; dez jobs = dez FFmpeg no processo da API. |
| Guarda de URL duplicada | 7 | Dois cliques = dois downloads e duas transcrições pagas. |
| Caminhos relativos ao CWD | 9 | `STORAGE_DIR=./storage` e o SQLite dependem do diretório de trabalho: rodar da raiz cria um banco vazio em silêncio. É decisão de deploy. |

---

## Pendência conhecida

Restam **9 transcrições órfãs** no banco de desenvolvimento, anteriores a estas
correções (com os JSONs ainda em disco). As correções impedem que novas
apareçam, mas não limpam as antigas. A limpeza depende de decisão do dono dos
dados e cabe naturalmente na Fatia 7, junto do TTL.
