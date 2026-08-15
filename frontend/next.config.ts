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
const backendPort = rootEnv.BACKEND_PORT || "8001";

const nextConfig: NextConfig = {
  // Só a senha: o resto do .env da raiz é do backend e não tem por que
  // atravessar para o bundle do frontend.
  env: { CLIPMINT_PASSWORD: rootEnv.CLIPMINT_PASSWORD ?? "" },

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
