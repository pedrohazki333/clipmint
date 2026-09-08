/**
 * A copy da landing, em um lugar só.
 *
 * Cada frase daqui foi aprovada palavra por palavra e é verificada contra o
 * documento da Landing V2 — inclusive a pontuação. Ficam juntas por isso: com o
 * texto espalhado por doze componentes, revisar uma troca de palavra vira uma
 * caçada, e foi assim que "prontos para publicar" já virou "pronto pra postar"
 * em metade das telas.
 *
 * O que NÃO pode entrar aqui: promessa de viralização, de crescimento ou de
 * dinheiro, e qualquer verbo que sugira que o ClipMint publica sozinho. Ele
 * entrega o clipe; quem posta é a pessoa.
 */

export const HERO = {
  eyebrow: "Clips verticais a partir de vídeos longos",
  headline: "Um vídeo longo. Vários clips prontos para publicar.",
  sub:
    "O ClipMint percorre o seu podcast ou gameplay inteiro, encontra os " +
    "trechos que valem um corte e entrega cada um em 9:16, legendado e com a " +
    "sua marca.",
  ctaPrimary: "Começar grátis",
  ctaSecondary: "Ver como funciona",
  microcopy: "120 créditos grátis. Sem cartão.",
  /** As duas rubricas, como pílulas logo abaixo da arte. */
  nichos: ["Podcast", "Gameplay"],
} as const;

/**
 * Como funciona — o par de blocos que o Opus chama de "editing models".
 *
 * Duas ideias e só duas: ele ACHA o momento, e ele MONTA o vertical. Tudo que o
 * produto faz cabe numa das duas, e separá-las é o que deixa cada arte com um
 * assunto só.
 */
export const METODO = {
  eyebrow: "Como funciona",
  title: "Ele não corta no palpite.",
  sub:
    "São duas coisas, e o ClipMint faz as duas sozinho: achar o trecho que " +
    "merece virar clipe, e montar esse trecho em vertical.",
  blocos: [
    {
      nome: "Acha o momento",
      texto:
        "A transcrição inteira é lida e cada trecho recebe uma nota. Só os " +
        "que passam da nota mínima do seu nicho viram clipe — um vídeo sem " +
        "nenhum momento forte devolve nenhum, e diz por quê.",
    },
    {
      nome: "Monta o vertical",
      texto:
        "O corte sai em 9:16 com legenda no ritmo da fala e o enquadramento " +
        "acompanhando quem está falando. No gameplay, a facecam vai para cima " +
        "e o jogo para baixo.",
    },
  ],
} as const;

/**
 * A rubrica — a nossa prova, no lugar onde a referência põe depoimento.
 *
 * O Opus prova com 16 milhões de criadores; nós não temos isso e não vamos
 * fingir que temos. O que temos é uma coisa que eles não mostram: o porquê de
 * cada corte. Isso é verificável na primeira geração, e é o argumento honesto
 * disponível para um produto novo.
 */
export const RUBRICA = {
  eyebrow: "A rubrica",
  title: "Você vê a nota e o motivo de cada corte.",
  sub:
    "Cada trecho é pontuado em cinco eixos antes de virar clipe, e o que " +
    "passa vem com a justificativa escrita. Você não recebe uma pilha de " +
    "cortes para conferir na mão — recebe a escolha e o critério dela.",
  eixos: [
    { nome: "Gancho", hint: "Força nos 3 primeiros segundos" },
    { nome: "Retenção", hint: "Segura a atenção até o fim" },
    { nome: "Compart.", hint: "Eu mandaria isso pra alguém" },
    { nome: "Comentários", hint: "Gera debate ou reação" },
    { nome: "Loop", hint: "O fim reconecta com o início" },
  ],
} as const;

export const AUDIENCES = {
  title: "Feito para quem já clipa. E para quem quer começar.",
  blocos: [
    { pergunta: "Já é clipador?", resposta: "Produza mais em menos tempo." },
    {
      pergunta: "Ainda não é?",
      resposta: "O ClipMint tira a parte pesada do caminho.",
    },
  ],
} as const;

export const NICHES = {
  title: "Feito para os conteúdos que mais pedem clips.",
  podcast: {
    nome: "Podcast",
    texto: "Transforme conversas longas em momentos que merecem virar clip.",
  },
  gameplay: {
    nome: "Gameplay",
    texto:
      "Encontre momentos relevantes mesmo quando a tela está cheia de ação.",
  },
} as const;

export const SETUP = {
  title: "Configure seu jeito de clipar. Depois, é só gerar.",
  mensagem: "Seu conteúdo, suas regras, seu estilo.",
  /** O fluxo conceitual — os quatro rótulos são exatamente os aprovados. */
  fluxo: ["Seu conteúdo", "Suas regras", "ClipMint", "Vários clips"],
  sub:
    "Cor do banner, fonte, logo e o formato do corte ficam salvos num perfil. " +
    "Você acerta uma vez e todo clipe daquele canal sai assim.",
} as const;

export const RESULT = {
  title: "Um vídeo longo. Vários momentos para publicar.",
  sub:
    "O ClipMint encontra trechos relevantes e entrega clips verticais prontos " +
    "para você continuar seu fluxo de publicação.",
  /** Indicadores de apoio. Não competem com o clipe — são legenda dele. */
  indicadores: [
    "Vertical 9:16",
    "Legendas",
    "Momento encontrado",
    "Pronto para publicar",
  ],
} as const;

export const PRODUCTIVITY = {
  title: "Mais conteúdo. Sem transformar isso em mais trabalho.",
  texto:
    "Um vídeo longo pode render vários clips. O ClipMint automatiza a parte " +
    "mais pesada do processo para você produzir mais sem precisar passar " +
    "horas procurando, cortando e preparando cada trecho.",
  ideias: [
    { forte: "Mais clips", fraco: "por vídeo" },
    { forte: "Menos trabalho", fraco: "manual" },
    { forte: "Mais oportunidades", fraco: "para publicar" },
  ],
} as const;

export const MOBILE = {
  title: "Clipar não precisa te prender ao computador.",
  texto:
    "Use o ClipMint direto do navegador, no Android ou no iPhone. Crie seus " +
    "perfis, gere clips e acompanhe seus resultados onde estiver.",
} as const;

/**
 * Os 120 são o bônus de cadastro real, não um número de marketing: vêm de
 * `creditos_gratis_cadastro` em `backend/app/services/billing.py`. Se um dia
 * ele mudar lá, as quatro aparições aqui (seção de créditos, FAQ, microcopy do
 * CTA final) mudam junto — é o preço de escrever o número por extenso, e
 * escrever por extenso é o que deixa a frase aprovada intacta.
 */
export const CREDITS = {
  title: "Simples de entender. Fácil de começar.",
  regra: "1 crédito = 1 minuto de vídeo processado.",
  numero: "120",
  rotulo: "créditos grátis",
  complemento: "para começar.",
} as const;

export const FAQ = {
  title: "Perguntas frequentes",
  itens: [
    {
      pergunta: "O ClipMint funciona com quais vídeos?",
      resposta:
        "O ClipMint é focado em podcasts e gameplays publicados no YouTube.",
    },
    {
      pergunta: "Preciso saber editar vídeo?",
      resposta:
        "Não. O ClipMint automatiza a parte pesada da busca, corte e " +
        "preparação dos clips.",
    },
    {
      pergunta: "Preciso instalar alguma coisa?",
      resposta:
        "Não. O ClipMint funciona direto pelo navegador, no computador ou no " +
        "celular.",
    },
    {
      pergunta: "Como funcionam os créditos?",
      resposta:
        "Cada crédito corresponde a 1 minuto de vídeo de origem processado. " +
        "Novos usuários começam com 120 créditos gratuitos.",
    },
    {
      pergunta: "Posso escolher como meus clips serão gerados?",
      resposta:
        "Sim. Você cria um perfil e define as configurações que serão " +
        "utilizadas na geração dos clips.",
    },
  ],
} as const;

export const FINAL_CTA = {
  eyebrow: "Pronto para começar?",
  headline:
    "Seu próximo clip pode começar com um vídeo que você já tem.",
  texto:
    "Comece grátis, configure seu perfil e deixe o ClipMint cuidar da parte " +
    "pesada.",
  cta: "Começar grátis",
  microcopy: "120 créditos grátis para começar.",
} as const;
