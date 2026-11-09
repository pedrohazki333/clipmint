import GerarWorkspace from "@/components/gerar/GerarWorkspace";

export const metadata = { title: "Gerar clipes — ClipMint" };

/**
 * Gerar clipes, com ou sem perfil. `?perfil=<id>` abre com ele escolhido — é por
 * onde chegam o botão "Gerar" de um perfil e o antigo /perfis/<id>/gerar.
 */
export default async function GerarPage({
  searchParams,
}: {
  searchParams: Promise<{ perfil?: string | string[] }>;
}) {
  const { perfil } = await searchParams;
  return <GerarWorkspace perfilInicial={typeof perfil === "string" ? perfil : undefined} />;
}
