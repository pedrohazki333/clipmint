import type { KeyboardEvent } from "react";

/**
 * O teclado de um grupo de rádio, como o padrão ARIA pede: o grupo é UMA parada
 * de Tab (a opção escolhida), e as setas trocam a escolha e levam o foco junto.
 * Sem isto, quatro cartões de legenda e cinco de layout viravam nove Tabs para
 * chegar ao botão de gerar.
 */
export function radioKeyDown<T>(
  e: KeyboardEvent<HTMLElement>,
  values: readonly T[],
  current: T,
  onChange: (value: T) => void,
) {
  const passo =
    e.key === "ArrowRight" || e.key === "ArrowDown"
      ? 1
      : e.key === "ArrowLeft" || e.key === "ArrowUp"
        ? -1
        : 0;
  if (!passo) return;
  e.preventDefault();
  const i = values.indexOf(current);
  const proximo = values[(i + passo + values.length) % values.length];
  onChange(proximo);
  const grupo = e.currentTarget.closest('[role="radiogroup"]');
  const botoes = grupo?.querySelectorAll<HTMLElement>('[role="radio"]');
  botoes?.[values.indexOf(proximo)]?.focus();
}
