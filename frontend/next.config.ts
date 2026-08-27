import { readFileSync } from "node:fs";
import { resolve } from "node:path";

import type { NextConfig } from "next";

/**
 * O Next só carrega .env de dentro de `frontend/`, mas a fonte de verdade das
 * configurações do projeto é o .env da raiz (compartilhado com o backend).
 * Lê e injeta aqui para não haver duas cópias da senha para manter em sincronia.
 */
function loadRootEnv(): Record<string, string> {
  const loaded: Record<string, string> = {};
  // process.cwd() é o diretório do frontend — o Next dev/build sempre roda a
  // partir dele. Evita __dirname, que não existe quando o config vira ESM.
  const envPath = resolve(process.cwd(), "..", ".env");
  let raw: string;
  try {
    raw = readFileSync(envPath, "utf-8");
  } catch (err) {
    console.warn(`[clipmint] não consegui ler ${envPath}:`, err);
    return loaded; // o middleware barra o acesso e explica o motivo
  }

  for (const line of raw.split("\n")) {
    const trimmed = line.trim();
    if (!trimmed || trimmed.startsWith("#")) continue;
    const eq = trimmed.indexOf("=");
    if (eq === -1) continue;
    const key = trimmed.slice(0, eq).trim();
    const value = trimmed.slice(eq + 1).trim().replace(/^["']|["']$/g, "");
    // Variável já exportada no shell vence o arquivo.
    loaded[key] = process.env[key] ?? value;
  }
  return loaded;
}

const rootEnv = loadRootEnv();

if (!rootEnv.CLIPMINT_PASSWORD) {
  console.warn(
    "[clipmint] CLIPMINT_PASSWORD vazia — o app vai responder 503 até ela ser definida no .env da raiz.",
  );
}

// Mesma porta que o Makefile passa para o uvicorn — ambos leem do .env da raiz.
// O default evita a 8000, que qualquer outro projeto FastAPI da máquina toma
// primeiro: o proxy cairia na API do vizinho e o app pareceria vazio.
//
// `process.env` primeiro, pelo mesmo motivo que PUBLIC_BUILD logo abaixo: o
// loadRootEnv só consulta o shell para chaves que JÁ existem no .env, e sem
// isto subir os dois builds lado a lado é impossível — o segundo servidor
// mandaria as chamadas para o backend do primeiro.
const backendPort = process.env.BACKEND_PORT || rootEnv.BACKEND_PORT || "8001";

/**
 * Este build é o PESSOAL (com Siege X e Melhorar vídeo) ou o PÚBLICO?
 *
 * Lido do .env da raiz — o MESMO arquivo que dá PUBLIC_BUILD ao backend — para
 * as duas metades não divergirem. A flag do backend é `PUBLIC_BUILD`; aqui a
 * pergunta é invertida porque o default do Next tem que ser o build restrito:
 * um .env que não carregou não pode publicar as features pessoais por omissão.
 */
// `process.env` primeiro: o loadRootEnv só consulta o shell para chaves que JÁ
// existem no arquivo, então `PUBLIC_BUILD=true npm run build` seria ignorado
// enquanto a chave não estivesse escrita no .env — e o build sairia pessoal
// achando que era público.
const personalBuild =
  (process.env.PUBLIC_BUILD ?? rootEnv.PUBLIC_BUILD ?? "").toLowerCase() !== "true";

console.log(
  `[clipmint] build ${personalBuild ? "PESSOAL (Siege X + Melhorar vídeo)" : "PÚBLICO"}`,
);

const nextConfig: NextConfig = {
  // Só a senha: o resto do .env da raiz é do backend e não tem por que
  // atravessar para o bundle do frontend.
  env: {
    // Só no build pessoal. O `env` do Next é INLINED em tempo de build, e o
    // build público não usa esta senha para nada — quem autentica lá é a sessão
    // de cada usuário. Injetá-la assaria um segredo dentro de um artefato que
    // não precisa dele. Verificado: ela não chega ao bundle do cliente em
    // nenhum dos dois casos, mas ficava no do servidor.
    CLIPMINT_PASSWORD: personalBuild ? rootEnv.CLIPMINT_PASSWORD ?? "" : "",
    // O tipo de build precisa chegar ao navegador: é ele que decide se a tela
    // de entrada pede uma senha compartilhada (pessoal) ou e-mail e senha de
    // uma conta (público). Um valor, não a senha — esta continua só no servidor.
    NEXT_PUBLIC_PUBLIC_BUILD: personalBuild ? "" : "1",
  },

  /**
   * Primeira camada da separação: as ROTAS.
   *
   * As páginas das features pessoais se chamam `page.personal.tsx`. O Next só
   * reconhece um arquivo como página quando o nome bate com `page.<ext>` para
   * algum `ext` desta lista — então, sem "personal.tsx" aqui, `page.personal.tsx`
   * não é rota, não é compilado e não aparece no manifesto. Com ela, a rota
   * existe normalmente. Não há `if` em lugar nenhum: a rota existe ou não.
   *
   * O mesmo vale para `route.personal.ts`: a tela de senha única do build
   * pessoal (`/auth/login` e `/auth/logout`) não existe no público, onde quem
   * autentica é a sessão de cada usuário.
   */
  pageExtensions: personalBuild
    ? ["personal.tsx", "personal.ts", "tsx", "ts"]
    : ["tsx", "ts"],

  /**
   * Cada variante escreve num diretório próprio.
   *
   * Sem isto, `PUBLIC_BUILD=true npm run build` sobrescreve o `.next` que o
   * `next dev` da versão pessoal está usando naquele momento — e o dev server
   * passa a responder 500 em toda página, porque encontra artefato de produção
   * onde esperava o dele. Aconteceu ao verificar esta própria separação.
   */
  distDir: process.env.NEXT_DIST_DIR ?? (personalBuild ? ".next" : ".next-public"),

  /**
   * Segunda camada: o CÓDIGO COMPARTILHADO.
   *
   * A home precisa saber quais cards mostrar, e essa lista cita as features
   * pessoais. Em vez de um `if` (que deixaria os nomes e as URLs no bundle como
   * código morto), `@/personal` é trocado por um stub de listas vazias: o módulo
   * real não é resolvido, então não existe nada para o bundler incluir.
   *
   * É um NormalModuleReplacementPlugin, e não um `resolve.alias`. O alias perde
   * para o resolvedor de `paths` do tsconfig (o `@/*` que o Next instala como
   * resolve plugin) e o módulo real entrava no bundle assim mesmo — verificado
   * procurando "siege" no .next. Este plugin age depois da resolução, então não
   * depende dessa ordem.
   *
   * O `$` do regex limita a troca ao próprio `@/personal`: `@/personal/api` e
   * `@/personal/types` continuam resolvendo normalmente, e só são alcançáveis a
   * partir de arquivos que o build público já não compila.
   */
  webpack(config, { webpack }) {
    if (!personalBuild) {
      config.plugins.push(
        new webpack.NormalModuleReplacementPlugin(
          /^@\/personal$/,
          resolve(process.cwd(), "src", "personal.stub.ts"),
        ),
      );
    }
    return config;
  },

  async rewrites() {
    return [
      {
        source: "/api/:path*",
        destination: `http://localhost:${backendPort}/api/:path*`,
      },
    ];
  },
};

export default nextConfig;
