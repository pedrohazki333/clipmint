# Layouts de clipe v2

Especificação aprovada pelo dono em 08/11/2026. As medidas mandam. Mockups de
referência (`docs/layouts/A.png` e `B.png`, em 405x720) ainda não estão no
repositório.

## Especificação visual (px no quadro de 1080x1920)

Áreas seguras do TikTok, onde nada importante pode cair: topo 150px, coluna da
direita 150px de largura (entre y=800 e y=1500), base 400px.

Fonte: Archivo (Google Fonts, variável, licença OFL), instalada junto das outras
fontes do branding. Títulos: peso 900, largura 75–78%, caixa alta. Legenda: peso
800, largura 92%.

### Layout A — "Tela cheia" (modo novo, `fullscreen`)

- Quem fala ocupa 1080x1920, com o face tracking existente
  (`services/face_tracker.py`) guiando o recorte 9:16.
- Título no topo: x=53, y=197, largura máxima até x=909. Fonte de 72px, line-height
  1.32, texto branco dentro de caixa #0B0B0C com padding 8px/24px, uma caixa por
  linha. Uma palavra-chave do título na cor da marca.
- @ do perfil uma vez só, logo abaixo do título: 32px, peso 700, branco com sombra
  leve.
- Legenda: centro em y≈1205, 88px, contorno preto de ~9px.

### Layout B — "Capa + faixa" (evolução do `cover`, mantém o mesmo id)

- A capa é uma PRÉVIA: um quadro parado do momento de reação mais forte que acontece
  DENTRO do clipe (risada, choque, surpresa). Ela promete o que vem.
- Em cima: capa, 1080x800.
- Faixa do título: 1080x256, fundo #0B0B0C, borda de 8px na cor da marca em cima e
  embaixo. Título com 67px, peso 900, largura 75%, branco, palavra-chave na cor da
  marca. @ uma vez só, 29px, #C9C9CF. Remova a faixa atual com o @ repetido.
- Embaixo: quem fala, 1080x864, com face tracking.
- Legenda: centro em y≈1205, 80px.

Regra de escolha da capa:

1. Procure o quadro de reação dentro do intervalo do clipe, priorizando os momentos
   de áudio alto (risada, grito).
2. Prefira um rosto DIFERENTE de quem fala embaixo naquele trecho (num podcast com
   corte de câmera, é o close do outro participante).
3. Se só houver o rosto de quem fala, use a expressão mais forte dele, nunca um
   quadro neutro de fala.
4. Registre no log qual regra decidiu a capa.

### Legenda (vale para todos os layouts)

- Estilo "cor": a palavra falada muda de cor.
- Estilo "caixa": a palavra falada ganha uma caixa na cor escolhida, texto #0B0B0C,
  padding 0 19px, raio 19px.
- Paleta: rosa #FD375C, amarelo #FFD23F, ciano #3EC8FF, verde #9DFF4F, mais cor livre.
- "Caixa" é mais uma opção e não elimina nada que já existe: os modos
  `word_highlight`, `traditional` e `none` continuam.

## Estilo do clipe por perfil

Um esquema só, validado no backend:

- layout: `fullscreen` (padrão do podcast) | `cover` | `streamer` | `crop` | `original`.
- marca (cor): padrão #FD375C.
- legenda: cor (padrão #FD375C), estilo `caixa` | `cor` (padrão `caixa`), tamanho
  P/M/G (M = medidas acima).
- título: ligado/desligado, com fundo (padrão #0B0B0C) e texto (padrão #FFFFFF). A
  palavra-chave em destaque vem da análise.
- @: texto e ligado/desligado.
- fonte: Archivo (padrão) e as que já existem no FontField.

Perfis existentes migram sem perder o que já configuraram. O banner azul com letra
amarela do `hzpodclips` é marca registrada e identidade da página: migra como fundo e
texto do título, e a legenda desse perfil usa "cor" em amarelo.

## Fatias

0. Este documento.
M. Memória: guarda antes do render, um render por vez, costura mais leve e checagem de
   processo que funcione no Windows.
1. Esquema de estilo por perfil + migração, sem mudar render ainda.
2. Layout A + legenda "cor" com cor configurável.
3. Layout B: faixa nova + regra nova da capa.
4. Legenda "caixa".
5. Tela de estilo no perfil com prévia ao vivo em CSS, nas mesmas medidas em escala
   0.375 (405x720).

## Critério de pronto (fatias 2, 3 e 4)

- Reprocessar o job do podcast da fatia anterior e entregar 1 quadro PNG de cada clipe
  no layout novo.
- Nada importante nas áreas seguras.
- Contraste do título e da legenda de pelo menos 4.5:1.
- No B: em pelo menos 2 de 3 clipes, a capa mostra uma pessoa diferente de quem fala
  embaixo.
- Suíte sem falhas novas.

Fora de escopo: identidade visual do site/app, landing page e cobrança.
