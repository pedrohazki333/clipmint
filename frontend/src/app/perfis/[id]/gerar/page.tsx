import { redirect } from "next/navigation";

/**
 * O endereço antigo de gerar a partir de um perfil. Continua valendo (há links
 * salvos e favoritos com ele) e leva à página de gerar com o perfil escolhido.
 */
export default async function GerarDoPerfil({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;
  redirect(`/gerar?perfil=${encodeURIComponent(id)}`);
}
