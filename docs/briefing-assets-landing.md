# Briefing de assets — Landing

Este arquivo é uma cópia de leitura. A fonte de verdade é
`frontend/src/components/marketing/assets.ts`, e a landing rodando já mostra
cada briefing no lugar exato onde a arte vai entrar.

**Como entregar:** coloque o arquivo no caminho indicado, com o nome exato.
Não precisa build, não precisa mexer em código, não precisa me chamar — o slot
troca o marcador pela arte no próximo carregamento.

**Regra das duas artes.** Onde existe linha `celular`, são DOIS arquivos: um
deitado e um em pé. Não é capricho — é o que separa uma página feita para o
celular de uma página espremida nele. Onde não existe linha `celular`, o
arquivo deitado serve aos dois.

**Estética:** fundo preto quase igual ao da página (`#0B0F0D`), luz baixa, verde
`#34D399` só como acento. Sem stock photo de gente sorrindo com headset, sem
"IA futurista", sem néon. A arte do hero que você já fez é a referência de tom.

---

## 1 · `hero` — imagem — **já entregue**

O episódio longo à esquerda e os clipes verticais saindo dele à direita.

| | |
|---|---|
| desktop | `public/landing/hero-visual.webp` · 1336×1002 · ✅ no lugar |
| celular | `public/landing/hero-visual-mobile.webp` · 1080×1350 · **falta** |

A versão em pé é a mais urgente da lista: hoje o celular recebe a deitada e a
arte fica pequena no primeiro quadro da página. Mesma cena, recomposta em
retrato — o player em cima, os clipes embaixo.

## 2 · `momento` — **vídeo**

A varredura acontecendo: a linha do tempo do episódio sendo percorrida e alguns
trechos acendendo como escolhidos. Precisa dar a sensação de que alguma coisa
está procurando, não de que uma tela está parada.

| | |
|---|---|
| desktop | `public/landing/momento.mp4` · 1600×1200 (+ `momento-poster.webp`) |
| celular | `public/landing/momento-mobile.mp4` · 1080×1350 (+ `momento-mobile-poster.webp`) |

Mudo, em laço, 4 a 8 segundos. H.264, sem áudio.

## 3 · `vertical` — **vídeo**

O antes e o depois lado a lado: o quadro deitado virando o clipe em pé, a
legenda entrando palavra por palavra, o corte acompanhando o rosto. É o único
lugar da página onde movimento explica melhor que foto.

| | |
|---|---|
| desktop | `public/landing/vertical.mp4` · 1600×1200 (+ `vertical-poster.webp`) |
| celular | `public/landing/vertical-mobile.mp4` · 1080×1350 (+ `vertical-mobile-poster.webp`) |

## 4 · `rubrica` — imagem — **a mais importante depois do hero**

O card de resultado em close: a nota grande, os cinco eixos, a frase de gancho
entre aspas e o motivo escrito.

| | |
|---|---|
| desktop | `public/landing/rubrica.webp` · 1400×1050 |
| celular | `public/landing/rubrica-mobile.webp` · 1080×1350 |

Esta arte carrega a única prova que temos hoje: que o ClipMint explica a
escolha. Pode ser captura de tela real do produto, tratada — e talvez seja
melhor que ilustração, justamente por ser real.

## 5 · `podcast` — imagem

Uma conversa de podcast com o momento escolhido em destaque. Estúdio, luz baixa.

`public/landing/podcast.webp` · 1200×1200 · (sem versão em pé; é quadrada)

## 6 · `gameplay` — imagem

Tela de jogo em ação com a facecam do jogador marcada no canto — é o que o
rastreador encontra e leva para a metade de cima do clipe.

`public/landing/gameplay.webp` · 1200×1200 · (sem versão em pé; é quadrada)

## 7 · `marca` — imagem

O MESMO clipe repetido três vezes com marcas diferentes: cor do banner, fonte e
logo trocadas. A ideia: você configura uma vez e todo clipe sai assim.

| | |
|---|---|
| desktop | `public/landing/marca.webp` · 1500×1000 |
| celular | `public/landing/marca-mobile.webp` · 1080×1350 |

## 8 · `celular` — imagem

Uma mão segurando um celular com o ClipMint aberto **no navegador**, na tela de
acompanhamento do job. Tem que ser reconhecível como navegador, não como app
instalado — o produto roda na web e a seção existe para dizer isso.

| | |
|---|---|
| desktop | `public/landing/celular.webp` · 1400×1050 |
| celular | `public/landing/celular-mobile.webp` · 1080×1350 |

---

## Ordem de prioridade

1. `hero-visual-mobile` — o primeiro quadro no celular está fraco hoje
2. `rubrica` — é o argumento que nos diferencia
3. `vertical` — a transformação, que é o que o produto faz
4. `momento`
5. `marca`, `celular`
6. `podcast`, `gameplay`

Com os três primeiros a página já para de parecer inacabada.
