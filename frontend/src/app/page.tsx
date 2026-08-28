import { cookies } from "next/headers";

import { AUTH_COOKIE } from "@/lib/auth";
import { IS_PUBLIC_BUILD, SESSION_COOKIE } from "@/lib/build";
import LandingPage from "@/components/marketing/LandingPage";
import PerfisDashboard from "@/components/PerfisDashboard";

/**
 * "/" decide entre a landing pública e o dashboard, sem duas rotas.
 *
 * No build pessoal o middleware já barra "/" sem a senha — quem chega aqui
 * está sempre logado, então cai direto no dashboard, como sempre foi. Só o
 * build público deixa "/" passar sem sessão (ver MARKETING_PATHS em
 * middleware.ts), e é aí que a landing aparece.
 */
export default async function Home() {
  const loggedIn = (await cookies()).has(
    IS_PUBLIC_BUILD ? SESSION_COOKIE : AUTH_COOKIE,
  );

  if (IS_PUBLIC_BUILD && !loggedIn) return <LandingPage />;
  return <PerfisDashboard />;
}
