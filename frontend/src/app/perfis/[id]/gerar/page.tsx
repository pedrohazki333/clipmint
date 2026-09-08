import ProfileGenerate from "@/components/ProfileGenerate";

export const metadata = { title: "Gerar clipes — ClipMint" };

export default async function GerarPage({
  params,
  searchParams,
}: {
  params: Promise<{ id: string }>;
  searchParams: Promise<{ url?: string }>;
}) {
  const { id } = await params;
  // Último trecho da jornada que começou no campo de link da landing: a URL
  // chega preenchida e a pessoa só confirma. Lida no servidor, então não
  // precisa de Suspense nem de estado no cliente.
  const { url } = await searchParams;
  return <ProfileGenerate profileId={id} defaultUrl={url} />;
}
