import { IS_PUBLIC_BUILD } from "@/lib/build";
import LandingPage from "@/components/marketing/LandingPage";

/**
 * "/" é a landing, e só ela.
 *
 * Antes esta rota decidia entre landing e dashboard olhando o cookie. Não decide
 * mais: quem tem sessão é redirecionado para /dashboard pelo middleware antes de
 * chegar aqui, e o build pessoal (que não tem landing) também. Uma URL, um
 * significado.
 *
 * O `IS_PUBLIC_BUILD` sobrou como cinto de segurança: se algum dia o middleware
 * deixar passar no build pessoal, o certo é não mostrar a vitrine de um produto
 * que ali não existe.
 */
export default function Home() {
  if (!IS_PUBLIC_BUILD) return null;
  return <LandingPage />;
}
