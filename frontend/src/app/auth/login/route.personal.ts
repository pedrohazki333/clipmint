import { NextResponse } from "next/server";

import { AUTH_COOKIE, deriveToken, safeEqual } from "@/lib/auth";

/** 30 dias — o notebook remoto não precisa relogar toda hora. */
const SESSION_MAX_AGE = 60 * 60 * 24 * 30;

export async function POST(req: Request) {
  const password = process.env.CLIPMINT_PASSWORD;
  if (!password) {
    return NextResponse.json(
      { error: "CLIPMINT_PASSWORD não configurada no servidor" },
      { status: 503 },
    );
  }

  let submitted: unknown;
  try {
    submitted = (await req.json())?.password;
  } catch {
    return NextResponse.json({ error: "Requisição inválida" }, { status: 400 });
  }

  if (typeof submitted !== "string" || !safeEqual(submitted, password)) {
    return NextResponse.json({ error: "Senha incorreta" }, { status: 401 });
  }

  const res = NextResponse.json({ ok: true });
  res.cookies.set(AUTH_COOKIE, await deriveToken(password), {
    httpOnly: true,
    sameSite: "lax",
    path: "/",
    maxAge: SESSION_MAX_AGE,
    // Sem `secure`: o acesso remoto é HTTP puro sobre a rede privada do
    // Tailscale. Marcar secure aqui impediria o cookie de ser gravado.
  });
  return res;
}
