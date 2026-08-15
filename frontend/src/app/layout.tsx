import type { Metadata } from "next";
import { cookies } from "next/headers";

import { AUTH_COOKIE } from "@/lib/auth";
import "./globals.css";

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
  const loggedIn = (await cookies()).has(AUTH_COOKIE);

  return (
    <html lang="pt-BR">
      <body className="min-h-screen bg-gray-950 text-gray-100 antialiased">
        <header className="border-b border-gray-800 px-6 py-4">
          <div className="mx-auto max-w-4xl flex items-center gap-3">
            <span className="text-2xl font-bold text-emerald-400">ClipMint</span>
            <span className="text-sm text-gray-500">viral clip generator</span>
            {loggedIn && (
              <form action="/auth/logout" method="post" className="ml-auto">
                <button
                  type="submit"
                  className="text-sm text-gray-500 transition hover:text-gray-300"
                >
                  Sair
                </button>
              </form>
            )}
          </div>
        </header>
        <main className="mx-auto max-w-4xl px-6 py-8">{children}</main>
      </body>
    </html>
  );
}
