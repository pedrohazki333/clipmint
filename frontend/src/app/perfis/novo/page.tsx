import { Suspense } from "react";

import ProfileForm from "@/components/ProfileForm";

export const metadata = { title: "Criar perfil — ClipMint" };

export default function NovoPerfilPage() {
  // O formulário lê `?url=` (o link que veio do hero da landing), e
  // useSearchParams exige Suspense no App Router.
  return (
    <Suspense>
      <ProfileForm />
    </Suspense>
  );
}
