import Link from "next/link";

import { ROTA_CADASTRO, ROTA_LOGIN } from "@/lib/rotas";

/**
 * A navbar de quem ainda não entrou.
 *
 * Quatro elementos e nada mais: a marca, a explicação, a porta de quem já tem
 * conta e o CTA. Um menu de categorias aqui não teria o que listar — o produto
 * tem uma landing, um tutorial e um login.
 *
 * Grudada no topo porque o CTA precisa continuar alcançável depois de dez telas
 * de scroll; fundo sólido, sem desfoque, para não virar vidro sobre o conteúdo.
 *
 * Quem TEM sessão nunca vê esta barra: `AppShell` entrega a ela o cabeçalho do
 * produto, com saldo e conta. A decisão está lá, em um lugar só.
 *
 * `largura` existe porque as duas páginas abertas têm medidas diferentes: a
 * landing é larga (1152), o tutorial continua na largura do produto (896). A
 * marca do cabeçalho tem que nascer na mesma coluna em que o título da página
 * começa — desalinhadas, as duas parecem de sites diferentes.
 */
const COLUNA = {
  landing: "mx-auto w-full max-w-6xl px-5 sm:px-8",
  app: "mx-auto w-full max-w-4xl px-4 sm:px-6",
} as const;

export default function MarketingHeader({
  largura = "landing",
}: {
  largura?: keyof typeof COLUNA;
}) {
  return (
    <header className="sticky top-0 z-50 border-b border-line bg-base">
      <div className={COLUNA[largura]}>
        <div className="flex h-14 items-center gap-4 sm:h-16">
          <Link href="/" className="text-title font-semibold text-mint">
            ClipMint
          </Link>

          <nav className="ml-auto flex items-center gap-2 sm:gap-4">
            <Link
              href="/como-funciona"
              className="hidden px-1 py-2 text-body text-ink-dim transition-colors hover:text-ink sm:inline-block"
            >
              Como funciona
            </Link>
            <Link
              href={ROTA_LOGIN}
              className="px-1 py-2 text-body text-ink-dim transition-colors hover:text-ink"
            >
              Entrar
            </Link>
            <Link
              href={ROTA_CADASTRO}
              className="rounded-sm bg-mint-strong px-3.5 py-2 text-body font-medium text-on-mint transition-colors hover:bg-mint sm:px-4"
            >
              Começar grátis
            </Link>
          </nav>
        </div>
      </div>
    </header>
  );
}
