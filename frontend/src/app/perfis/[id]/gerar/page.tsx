import ProfileGenerate from "@/components/ProfileGenerate";

export const metadata = { title: "Gerar clipes — ClipMint" };

export default async function GerarPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;
  return <ProfileGenerate profileId={id} />;
}
