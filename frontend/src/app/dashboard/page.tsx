import PerfisDashboard from "@/components/PerfisDashboard";

export const metadata = { title: "Meus perfis — ClipMint" };

/**
 * A casa de quem está logado.
 *
 * Saiu de "/" para cá: a raiz agora é só a landing. Quem chega aqui sem sessão
 * já foi barrado pelo middleware, então esta página não decide nada — só
 * desenha.
 */
export default function DashboardPage() {
  return <PerfisDashboard />;
}
