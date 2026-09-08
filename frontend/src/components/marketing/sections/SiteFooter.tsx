import Link from "next/link";

import { ROTA_LOGIN } from "@/lib/rotas";
import { Container } from "../ui";

/**
 * Rodapé.
 *
 * Só o necessário: quem é, e as duas portas. Um mega-rodapé com colunas de
 * links seria uma seção de marketing a mais depois do CTA final — exatamente
 * onde a página já terminou de falar.
 */
export default function SiteFooter() {
  return (
    <footer className="border-t border-line py-10">
      <Container>
        <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
          <p className="text-label text-ink-dim">
            <span className="font-semibold text-mint">ClipMint</span> — clips
            verticais a partir de vídeos longos.
          </p>
          <nav className="flex items-center gap-5">
            <Link
              href="/como-funciona"
              className="text-label text-ink-dim transition-colors hover:text-ink"
            >
              Como funciona
            </Link>
            <Link
              href={ROTA_LOGIN}
              className="text-label text-ink-dim transition-colors hover:text-ink"
            >
              Entrar
            </Link>
          </nav>
        </div>
      </Container>
    </footer>
  );
}
