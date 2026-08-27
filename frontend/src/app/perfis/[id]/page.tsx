import ProfileView from "@/components/ProfileView";

export const metadata = { title: "Perfil — ClipMint" };

export default async function PerfilPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;
  return <ProfileView profileId={id} />;
}
