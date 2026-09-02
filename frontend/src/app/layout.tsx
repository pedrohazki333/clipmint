import type { Metadata } from "next";
import Link from "next/link";
import Script from "next/script";
import { cookies } from "next/headers";
import { IBM_Plex_Mono, IBM_Plex_Sans } from "next/font/google";

import { AUTH_COOKIE } from "@/lib/auth";
import { IS_PUBLIC_BUILD, SESSION_COOKIE } from "@/lib/build";
import CreditBalance from "@/components/CreditBalance";
import LogoutButton from "@/components/LogoutButton";
import UserMenu from "@/components/UserMenu";
import "./globals.css";

/**
 * Plex Sans para texto, Plex Mono para número e timecode.
 *
 * O mono não é enfeite: timecode, duração, as cinco notas da rubrica e a
 * contagem de views aparecem em cards repetidos, e em coluna eles precisam
 * alinhar. Ver `.tabular` em globals.css.
 *
 * Pelo next/font as fontes são hospedadas junto do app — nada é pedido a
 * terceiros em tempo de execução.
 */
const plexSans = IBM_Plex_Sans({
  subsets: ["latin", "latin-ext"],
  weight: ["400", "500", "600"],
  variable: "--font-plex-sans",
  display: "swap",
});

const plexMono = IBM_Plex_Mono({
  subsets: ["latin"],
  weight: ["400", "500"],
  variable: "--font-plex-mono",
  display: "swap",
});

export const metadata: Metadata = {
  title: "ClipMint",
  description: "Gere clips virais a partir de vídeos do YouTube",
};

export default async function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  // Só a presença do cookie: quem tem um valor inválido nem chega aqui, o
  // middleware já mandou para o login. Isto é só para não mostrar "Sair" nele.
  // Cada build tem o seu cookie — sessão de conta no público, senha única na
  // versão pessoal.
  const loggedIn = (await cookies()).has(
    IS_PUBLIC_BUILD ? SESSION_COOKIE : AUTH_COOKIE,
  );

  return (
    <html lang="pt-BR" className={`${plexSans.variable} ${plexMono.variable}`}>
      <body className="min-h-screen bg-base font-sans text-body text-ink antialiased">
        <header className="border-b border-line px-4 py-4 sm:px-6">
          <div className="mx-auto flex max-w-4xl items-center gap-3">
            <Link href="/" className="text-title font-semibold text-mint">
              ClipMint
            </Link>
            <span className="hidden text-label text-ink-muted sm:inline">
              cortes verticais a partir de vídeos longos
            </span>
            {/* Só existe landing e tutorial no build público — a versão
                pessoal não ganha este link, pois nunca mostra a landing. */}
            {IS_PUBLIC_BUILD && (
              <Link
                href="/como-funciona"
                className="text-label text-ink-dim transition-colors hover:text-ink"
              >
                Como usar
              </Link>
            )}
            {/* Público: saldo sempre à vista + botão de conta, ou CTA de
                cadastro para quem ainda não entrou. Pessoal: não há conta nem
                crédito, só a porta de saída da senha única.
                O saldo vem ANTES da conta porque é o que se consulta com
                frequência — a conta se abre uma vez por semana. */}
            <div className="ml-auto flex items-center gap-2">
              {loggedIn ? (
                <>
                  {IS_PUBLIC_BUILD && <CreditBalance />}
                  {IS_PUBLIC_BUILD ? <UserMenu /> : <LogoutButton />}
                </>
              ) : (
                IS_PUBLIC_BUILD && (
                  <Link
                    href="/login"
                    className="rounded-sm bg-mint-strong px-3 py-1.5 text-label font-medium text-base transition-colors hover:bg-mint"
                  >
                    Criar conta
                  </Link>
                )
              )}
            </div>
          </div>
        </header>
        <main className="mx-auto max-w-4xl px-4 py-6 sm:px-6 sm:py-8">
          {children}
        </main>

        {/*
          Analítica só no build PÚBLICO. Na versão pessoal ela mediria o uso do
          próprio dono e mandaria isso para fora — sem ganho nenhum, já que ali
          existe um usuário só.

          No navegador, e não no log do nginx, por um motivo medido: em três
          dias o log acumulou 245 IPs que pediram `/www/.env`, `/.git/config` e
          `/wp-config.php~` e sumiram. Robô não executa JavaScript, então medir
          aqui filtra a varredura sozinho, sem regra que eu tenha que manter.

          `afterInteractive` para não disputar com a hidratação; o beacon não
          usa cookie, então não puxa aviso de cookies junto.
        */}
        {IS_PUBLIC_BUILD && (
          <Script
            src="https://static.cloudflareinsights.com/beacon.min.js"
            strategy="afterInteractive"
            data-cf-beacon='{"token": "02c8ad33496a4ab7aeacb277cceb473e"}'
          />
        )}
      </body>
    </html>
  );
}
