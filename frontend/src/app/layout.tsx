import type { Metadata } from "next";
import Script from "next/script";
import { cookies } from "next/headers";
import { IBM_Plex_Mono, IBM_Plex_Sans } from "next/font/google";

import { AUTH_COOKIE } from "@/lib/auth";
import { IS_PUBLIC_BUILD, SESSION_COOKIE } from "@/lib/build";
import AppShell from "@/components/AppShell";
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
  // "Clips virais" prometia o resultado; o produto entrega a produção. É a
  // mesma linha que a landing sustenta, e é ela que aparece no resultado de
  // busca e no card compartilhado.
  description:
    "Transforme podcasts e gameplays em clips verticais prontos para publicar.",
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
        {/* Cabeçalho e moldura moram no AppShell: o produto e a vitrine usam
            barras diferentes, e a escolha entre as duas depende do caminho —
            que só o cliente conhece. Ver components/AppShell.tsx. */}
        <AppShell loggedIn={loggedIn}>{children}</AppShell>

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
