# Handoff — Landing V2 e design system

**Sessão de 08/09/2026.** Ponto de parada para retomar de outra máquina.
Branch: `landing-v2-design-system`. Base: `3e69133` (main).

---

## Em uma frase

A landing foi refeita duas vezes (a segunda seguindo o OpusClip como
referência), ganhou um sistema de assets com placeholders, e o produto começou a
receber o mesmo design system — com `/` virando landing pura, `/dashboard`
nascendo, a criação de perfil caindo de 14 campos para 2, e um preview ao vivo
do clipe.

## O que está pronto

### Landing (`frontend/src/components/marketing/`)
- 11 seções no ritmo do OpusClip: eyebrow pequeno → headline grande centralizada
  → uma linha de subtexto → **um asset grande por ideia**, com título e descrição
  abaixo do card.
- `assets.ts` — catálogo de TODAS as artes. `Asset.tsx` — o slot que as desenha,
  com arte separada para desktop e celular (`<source media>`, sem JS).
- Enquanto o arquivo não existe, o slot mostra o briefing e o caminho esperado.
- `HeroUrlForm` — campo de link no hero, validado pela mesma função do produto.
- `MobileCtaBar` — barra fixa que só existe no celular e só acende depois que o
  CTA do hero sai da tela.
- Copy centralizada em `copy.ts`.

### Rotas
- `/` = **só a landing**. Com sessão → 307 para `/dashboard`.
- `/dashboard` = a casa de quem entrou (era o antigo comportamento de `/`).
- `AppShell.tsx` decide entre a barra de marketing e a do produto.

### Produto
- `components/ui.tsx` — `Card`, `Button`, `Field`, `Input`, `Hint`, `ErroFaixa`.
- Criar perfil: **14 campos → 2** (nome e rubrica). O resto tem padrão e vive na
  edição.
- `ClipPreview.tsx` — o clipe 9:16 desenhado ao vivo, com geometria MEDIDA do
  render real (ver abaixo). Grudado no topo no celular, coluna direita no
  desktop.
- Primeiro uso: `Hint` nos campos + guia de três passos no dashboard vazio.

---

## Decisões já tomadas — não relitigar

1. **Nada de simular o produto com HTML/CSS/SVG.** A primeira versão desenhava
   as telas com `div` e foi rejeitada: fica fiel e fica morta. Todo visual da
   landing passa por `Asset` e carrega arquivo de verdade.
2. **O celular não é o desktop espremido.** Cada slot tem arte própria em pé;
   a barra de CTA existe só lá; o preview fica grudado no topo no celular.
3. **Prova de método, não de fama.** Sem depoimento inventado e sem logo de
   empresa que não é cliente. No lugar, a seção da rubrica — nota, cinco eixos e
   o motivo escrito de cada corte.
4. **Copy de produção, nunca de resultado.** Pode dizer "1 vídeo, vários clips",
   "sem abrir editor". Não pode dizer "viralize", "cresça", "ganhe dinheiro".
5. **Preview desenhado no front**, não renderizado pelo backend — instantâneo e
   sem custo. O limite conhecido está registrado abaixo.

## A geometria do preview (medida, não estimada)

Rodei `generate_banner` / `generate_divider_bar` / `streamer_geometry` e medi os
PNGs. Se mexer no render, remedir. As constantes estão no topo de
`ClipPreview.tsx`.

| | valor |
|---|---|
| Canvas | 1080×1920 |
| Capa (modo capa) | 0–768 (40%) |
| Banner | **1080×222, largura cheia, cantos vivos, CAIXA ALTA**, y=657 (34,219%) |
| Faixa da conta | 1080×54 (2,8125%) em y=879, o **@ repetido** com • e fio de luz |
| Facecam (streamer) | 0–672 (35%); faixa 672–726; jogo 726–1920 |
| Legenda | Arial bold, `MARGIN_V_WORD` 440 (22,917%), destaque **amarelo #FFFF00** a 112% |
| Caixa da legenda | **normal, não caixa alta** |

**Limite conhecido:** a quebra de linha do título é aproximada — quem quebra de
verdade é o Pillow com a fonte do servidor. Por isso `BANNER_H` está fixo nos
11,5625% de um título de DUAS linhas. Ao trocar o título de exemplo, conferir
com `generate_banner` que ele ainda dá 222px.

---

## Pendências

### 1. Assets (é o bloqueio principal)
Ver `docs/briefing-assets-landing.md`. Oito slots; só o `hero` desktop está no
lugar. Prioridade:
1. `hero-visual-mobile.webp` (1080×1350)
2. `rubrica.webp` + versão em pé
3. `vertical.mp4` + versão em pé

### 2. Design system nas telas restantes
`components/ui.tsx` só foi aplicado em criar/editar perfil e no dashboard.
Faltam `/conta`, `/recarga`, `/creditos`, job e geração.

### 3. Fluxo de geração
Ainda joga layout, legenda, modo de clipe e clipes manuais na mesma tela.

### 4. Jornada do link do hero — sem teste ponta a ponta
`HeroUrlForm` → `/login?modo=criar&url=` → `AccountForm` →
`/perfis/novo?url=` → `ProfileForm` → `/perfis/[id]/gerar?url=` → `UrlInput`.
Cada trecho passa o parâmetro adiante e o build está limpo, mas ninguém
percorreu com uma conta real.

### 5. Sujeira
Conta `qa-visual@clipmint.dev` no Postgres público (criada para ver as telas
autenticadas). Não há rota de apagar conta — remover no banco.

---

## Como subir

```bash
make build-public                    # gera .next-public
make _serve-public-backend           # uvicorn 127.0.0.1:8002
cd frontend && PUBLIC_BUILD=true PORT=3000 BACKEND_PORT=8002 npm run start
```

A porta é a **3000**, e não a 3001 do `make serve-public`: o localhost do
Windows não relaia a 3001 (ver `docs/` e a memória do projeto). Se o navegador
do Windows não abrir, usar o IP do WSL (`hostname -I`), que muda a cada boot.

## Armadilhas encontradas nesta sessão

- **Arquivo em `public/` fora do matcher do middleware vira página.** O asset do
  hero levava 307 para `/login`, e o sintoma aparecia torto: o otimizador de
  imagem do Next buscava o original por HTTP, pegava o redirect e devolvia
  `400 "The requested resource isn't a valid image"`. Corrigido incluindo
  `landing/` na exceção do matcher.
- **Trilha de grid em `auto` estoura a largura no celular.** A tela de edição
  ficou com `scrollWidth` 773px num viewport de 390 porque o texto longo
  dimensionava a coluna por `max-content`. Resolvido com
  `grid-cols-[minmax(0,1fr)]` e `min-w-0` nos filhos.
- **`next start` não recarrega o build.** Depois de `make build-public` é
  preciso matar e subir de novo, senão o servidor continua servindo o HTML
  antigo e referenciando um CSS que já não existe — a página abre sem estilo
  nenhum e a altura triplica.
