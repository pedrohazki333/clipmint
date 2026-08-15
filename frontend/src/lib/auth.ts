/**
 * Auth de senha única compartilhada.
 *
 * O cookie não guarda a senha: guarda um token derivado por HMAC. Assim o
 * middleware valida a sessão recomputando o token, sem precisar de storage —
 * e um vazamento do cookie não entrega a senha em si.
 *
 * Usa Web Crypto (não `node:crypto`) porque o middleware roda no runtime Edge.
 */

export const AUTH_COOKIE = "clipmint_auth";

/** Mensagem fixa do HMAC. Trocar isto invalida todas as sessões abertas. */
const AUTH_MESSAGE = "clipmint-auth-v1";

export async function deriveToken(password: string): Promise<string> {
  const enc = new TextEncoder();
  const key = await crypto.subtle.importKey(
    "raw",
    enc.encode(password),
    { name: "HMAC", hash: "SHA-256" },
    false,
    ["sign"],
  );
  const sig = await crypto.subtle.sign("HMAC", key, enc.encode(AUTH_MESSAGE));
  return Array.from(new Uint8Array(sig))
    .map((b) => b.toString(16).padStart(2, "0"))
    .join("");
}

/** Comparação de tempo constante — não sai mais cedo no primeiro byte diferente. */
export function safeEqual(a: string, b: string): boolean {
  if (a.length !== b.length) return false;
  let diff = 0;
  for (let i = 0; i < a.length; i++) diff |= a.charCodeAt(i) ^ b.charCodeAt(i);
  return diff === 0;
}
