import { NextResponse, type NextRequest } from "next/server";

import { AUTH_COOKIE, deriveToken, safeEqual } from "@/lib/auth";

/** Rotas que precisam ficar abertas para a própria tela de login funcionar. */
const PUBLIC_PATHS = new Set(["/login", "/auth/login", "/auth/logout"]);

export async function middleware(req: NextRequest) {
  const { pathname } = req.nextUrl;
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
