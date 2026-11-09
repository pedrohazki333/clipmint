import { redirect } from "next/navigation";

// Provisório: até a página nova de gerar existir, gerar continua começando pelo
// perfil, como antes.
export default function GerarPage() {
  redirect("/perfis");
}
