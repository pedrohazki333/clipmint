import { cookies } from "next/headers";
import { redirect } from "next/navigation";

import { AUTH_COOKIE } from "@/lib/auth";
import { IS_PUBLIC_BUILD, SESSION_COOKIE } from "@/lib/build";
import LandingPage from "@/components/marketing/LandingPage";

/**
 * "/" decide entre a landing pública e o app.
 *
 * Logado, a casa do app é "Gerar clipes": é a ação que se vem fazer, e a página
 * já mostra os últimos projetos ao lado. Os perfis, que moravam aqui, ficam em
 * /perfis. Só o build público deixa "/" passar sem sessão (ver MARKETING_PATHS em
 * middleware.ts), e é aí que a landing aparece.
 */
export default async function Home() {
  const loggedIn = (await cookies()).has(
    IS_PUBLIC_BUILD ? SESSION_COOKIE : AUTH_COOKIE,
  );

  if (IS_PUBLIC_BUILD && !loggedIn) return <LandingPage />;
  redirect("/gerar");
}
