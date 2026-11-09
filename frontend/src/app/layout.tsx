import type { Metadata } from "next";
import Script from "next/script";
import { cookies } from "next/headers";
import {
  Archivo,
  Barlow_Condensed,
  IBM_Plex_Mono,
  IBM_Plex_Sans,
  Inter,
  Space_Grotesk,
} from "next/font/google";

import { AUTH_COOKIE } from "@/lib/auth";
import { IS_PUBLIC_BUILD, SESSION_COOKIE } from "@/lib/build";
import Chrome from "@/components/shell/Chrome";
import "./globals.css";

/**
 * As fontes da direção "Editorial Tech", todas pelo next/font — hospedadas
 * junto do app, sem requisição a terceiros em tempo de execução.
 *
 *   - Inter: interface, rótulo, botão, corpo;
 *   - Space Grotesk: títulos e números em destaque;
 *   - Barlow Condensed 800: os títulos grandes de página ("GERAR CLIPES"). É
 *     condensada de verdade — nada de esticar texto com transform;
 *   - Plex Mono: timecode, duração e notas, que precisam alinhar em coluna
 *     (ver `.tabular` em globals.css);
 *   - Archivo: a fonte dos clipes, para as prévias saírem iguais ao render;
 *   - Plex Sans: só a landing, que segue no tema antigo até ser refeita.
 */
const inter = Inter({
  subsets: ["latin", "latin-ext"],
  variable: "--font-inter",
  display: "swap",
});

const spaceGrotesk = Space_Grotesk({
  subsets: ["latin", "latin-ext"],
  weight: ["500", "600", "700"],
  variable: "--font-space-grotesk",
  display: "swap",
});

const barlowCondensed = Barlow_Condensed({
  subsets: ["latin", "latin-ext"],
  weight: ["700", "800"],
  style: ["normal", "italic"],
  variable: "--font-barlow-condensed",
  display: "swap",
});

const plexMono = IBM_Plex_Mono({
  subsets: ["latin"],
  weight: ["400", "500"],
  variable: "--font-plex-mono",
  display: "swap",
});

const archivo = Archivo({
  subsets: ["latin", "latin-ext"],
  axes: ["wdth"],
  variable: "--font-archivo",
  display: "swap",
});

const plexSans = IBM_Plex_Sans({
  subsets: ["latin", "latin-ext"],
  weight: ["400", "500", "600"],
  variable: "--font-plex-sans",
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
  // middleware já mandou para o login. Cada build tem o seu cookie — sessão de
  // conta no público, senha única na versão pessoal.
  const loggedIn = (await cookies()).has(
    IS_PUBLIC_BUILD ? SESSION_COOKIE : AUTH_COOKIE,
  );

  const fontes = [
    inter.variable,
    spaceGrotesk.variable,
    barlowCondensed.variable,
    plexMono.variable,
    archivo.variable,
    plexSans.variable,
  ].join(" ");

  return (
    <html lang="pt-BR" className={fontes}>
      <body className="min-h-screen bg-base font-sans text-body text-ink antialiased">
        <Chrome loggedIn={loggedIn} publicBuild={IS_PUBLIC_BUILD}>
          {children}
        </Chrome>

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
