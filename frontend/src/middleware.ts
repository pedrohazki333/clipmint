import { NextResponse, type NextRequest } from "next/server";

import { AUTH_COOKIE, deriveToken, safeEqual } from "@/lib/auth";
import { IS_PUBLIC_BUILD, SESSION_COOKIE } from "@/lib/build";

/** Rotas que precisam ficar abertas para a própria tela de login funcionar. */
const PUBLIC_PATHS = new Set(["/login", "/auth/login", "/auth/logout"]);

/**
 * Landing e tutorial: abertas para visitante sem sessão, mas só no build
 * público. Entram apenas em `guardaPublica` — o build pessoal nunca deve
 * mostrar nada antes da senha, então esta lista não participa do branch
 * pessoal abaixo.
 */
const MARKETING_PATHS = new Set(["/", "/como-funciona"]);

/**
 * Recuperação de senha. Fora de PUBLIC_PATHS porque estas duas telas só existem
 * no build público: no pessoal a entrada é uma senha única compartilhada, que
 * não tem dono nem e-mail para onde mandar link.
 */
const RESET_PATHS = new Set(["/esqueci-senha", "/redefinir-senha"]);

/** Rotas de API da autenticação: sem elas ninguém consegue nem tentar entrar. */
const AUTH_API = new Set([
  "/api/auth/login",
  "/api/auth/register",
  "/api/auth/me",
  "/api/auth/logout",
  // Quem esqueceu a senha não tem sessão — é o estado inteiro do problema.
  "/api/auth/forgot-password",
  "/api/auth/reset-password",
]);

/**
 * Webhook do gateway de pagamento.
 *
 * Quem chama é o Mercado Pago, que não tem cookie de sessão e nunca terá:
 * passar por esta guarda é impossível para ele, e sem esta exceção a
 * notificação de pagamento morre aqui com 401, sem nunca chegar ao backend — o
 * usuário paga o Pix e o saldo não entra.
 *
 * Deixar a rota passar não abre nada: quem autentica ali é a assinatura HMAC do
 * próprio gateway, conferida no backend (services/mercadopago.py), que recusa
 * tudo quando o segredo não está configurado.
 */
const WEBHOOK_PATHS = new Set(["/api/billing/webhook"]);

/**
 * Guarda do build PÚBLICO.
 *
 * Aqui quem autentica de verdade é o backend, que valida a sessão contra a
 * tabela `sessions` a cada request. Este middleware só evita a ida inútil ao
 * servidor quando não há cookie nenhum — ele NÃO decide quem entra, e por isso
 * olha apenas a presença do cookie, nunca o conteúdo: julgar o valor aqui
 * duplicaria a autoridade em dois lugares que poderiam discordar.
 */
function guardaPublica(req: NextRequest): NextResponse {
  const { pathname } = req.nextUrl;

  if (
    PUBLIC_PATHS.has(pathname) ||
    MARKETING_PATHS.has(pathname) ||
    RESET_PATHS.has(pathname) ||
    AUTH_API.has(pathname) ||
    WEBHOOK_PATHS.has(pathname)
  ) {
    return NextResponse.next();
  }

  if (req.cookies.has(SESSION_COOKIE)) return NextResponse.next();

  if (pathname.startsWith("/api/")) {
    return NextResponse.json({ detail: "Faça login para continuar" }, { status: 401 });
  }

  const login = req.nextUrl.clone();
  login.pathname = "/login";
  login.search = pathname === "/" ? "" : `?next=${encodeURIComponent(pathname)}`;
  return NextResponse.redirect(login);
}

export async function middleware(req: NextRequest) {
  const { pathname } = req.nextUrl;

  if (IS_PUBLIC_BUILD) return guardaPublica(req);

  // ── Daqui para baixo: versão PESSOAL, com a senha única de sempre ──────────
  const password = process.env.CLIPMINT_PASSWORD;

  // Falha fechada: sem senha configurada, ninguém entra. O modo perigoso seria
  // liberar tudo — o app ficaria exposto justamente quando o .env não carregou.
  if (!password) {
    return new NextResponse(
      "CLIPMINT_PASSWORD não está definida no .env da raiz do projeto. " +
        "Defina e reinicie o frontend.",
      { status: 503, headers: { "content-type": "text/plain; charset=utf-8" } },
    );
  }

  if (PUBLIC_PATHS.has(pathname)) return NextResponse.next();

  const cookie = req.cookies.get(AUTH_COOKIE)?.value;
  if (cookie && safeEqual(cookie, await deriveToken(password))) {
    // O backend não pode identificar este proxy pelo IP: atrás de um túnel, o
    // X-Forwarded-For faz o uvicorn (--proxy-headers, ligado por padrão) trocar
    // o IP do cliente pelo do visitante externo. Então o proxy se autentica.
    const headers = new Headers(req.headers);
    headers.set("x-clipmint-token", password);
    return NextResponse.next({ request: { headers } });
  }

  // Chamada de API responde 401 em vez de redirecionar: o axios do frontend
  // engasgaria com o HTML da tela de login.
  if (pathname.startsWith("/api/")) {
    return NextResponse.json({ detail: "Sessão expirada" }, { status: 401 });
  }

  const login = req.nextUrl.clone();
  login.pathname = "/login";
  login.search = pathname === "/" ? "" : `?next=${encodeURIComponent(pathname)}`;
  return NextResponse.redirect(login);
}

export const config = {
  // Deixa passar os assets do Next e o favicon — o resto (páginas e /api/*) passa aqui.
  matcher: ["/((?!_next/static|_next/image|favicon.ico).*)"],
};
