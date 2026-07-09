import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "ClipMint",
  description: "Gere clips virais a partir de vídeos do YouTube",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="pt-BR">
      <body className="min-h-screen bg-gray-950 text-gray-100 antialiased">
        <header className="border-b border-gray-800 px-6 py-4">
          <div className="mx-auto max-w-4xl flex items-center gap-3">
            <span className="text-2xl font-bold text-emerald-400">ClipMint</span>
            <span className="text-sm text-gray-500">viral clip generator</span>
          </div>
        </header>
        <main className="mx-auto max-w-4xl px-6 py-8">{children}</main>
      </body>
    </html>
  );
}
