/**
 * As duas portas de entrada, com nome.
 *
 * "Entrar" e "Começar grátis" caem na MESMA rota — `/login` decide o formulário
 * pelo parâmetro. Antes os dois botões apontavam para `/login` seco, que abre
 * em "entrar": quem clicava em criar conta chegava numa tela pedindo a senha de
 * uma conta que ainda não existia, e precisava achar o "Criar uma conta" no
 * rodapé do formulário para sair dali. O parâmetro remove esse segundo clique.
 *
 * Constantes, e não strings soltas, porque quem escreve o link (navbar, hero,
 * CTA final, tutorial) nunca é quem lê o parâmetro (`AccountForm`).
 */

/** Abre o formulário no modo de login. */
export const ROTA_LOGIN = "/login";

/** Abre o formulário já no modo de criação de conta. */
export const ROTA_CADASTRO = "/login?modo=criar";

/**
 * A casa de quem está logado.
 *
 * Antes "/" era as duas coisas: landing para visitante, dashboard para quem
 * tinha sessão. Funcionava, mas cobrava caro — a mesma URL mudava de significado
 * conforme o cookie, o que atrapalha compartilhar link, medir a landing separada
 * do produto e cachear qualquer uma das duas. Agora "/" é só a landing e o
 * produto tem endereço próprio.
 */
export const ROTA_DASHBOARD = "/dashboard";
