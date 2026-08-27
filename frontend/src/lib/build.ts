/**
 * Qual build está rodando, do ponto de vista do navegador.
 *
 * Só isto atravessa para o cliente — a senha da versão pessoal continua sendo
 * lida apenas no servidor (middleware e route handlers).
 *
 * O valor é injetado pelo next.config a partir do PUBLIC_BUILD do .env da raiz,
 * o mesmo que o backend lê. As duas metades não têm como divergir.
 */
export const IS_PUBLIC_BUILD = process.env.NEXT_PUBLIC_PUBLIC_BUILD === "1";

/** Nome do cookie de sessão que o backend emite no build público. */
export const SESSION_COOKIE = "clipmint_session";
