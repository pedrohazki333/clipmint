"use client";

import { useEffect, useRef, useState, type ReactNode } from "react";

/**
 * Aparece quando entra na tela. Nada além disso.
 *
 * O CSS está em globals.css (`[data-reveal]`); aqui só existe a decisão de
 * quando marcar `data-shown`. Um observer por instância — são algumas dezenas
 * na página inteira, e cada um se desconecta no primeiro disparo, então a
 * página fica sem nenhum listener assim que o scroll passa.
 *
 * `once` é proposital: nada some ao rolar de volta. Elemento que reaparece a
 * cada scroll vira efeito de apresentação, e a direção aprovada é o contrário
 * disso — o movimento serve para explicar continuidade, não para chamar
 * atenção.
 */
export type RevealVariant = "up" | "left" | "right" | "fade";

interface Props {
  children: ReactNode;
  /** Para onde o elemento se desloca antes de aparecer. */
  variant?: RevealVariant;
  /** Milissegundos de atraso — só onde a ordem de leitura importa. */
  delay?: number;
  className?: string;
}

export default function Reveal({
  children,
  variant = "up",
  delay = 0,
  className,
}: Props) {
  const ref = useRef<HTMLDivElement>(null);
  const [shown, setShown] = useState(false);

  useEffect(() => {
    const el = ref.current;
    if (!el) return;

    // Navegador sem IntersectionObserver mostra tudo de imediato: o conteúdo
    // vale mais que a entrada dele.
    if (typeof IntersectionObserver === "undefined") {
      setShown(true);
      return;
    }

    const io = new IntersectionObserver(
      ([entrada]) => {
        if (!entrada.isIntersecting) return;
        setShown(true);
        io.disconnect();
      },
      // A margem negativa embaixo segura a revelação até o elemento estar
      // realmente dentro da leitura, e não só raspando a borda inferior.
      { rootMargin: "0px 0px -10% 0px", threshold: 0.08 },
    );
    io.observe(el);
    return () => io.disconnect();
  }, []);

  return (
    <div
      ref={ref}
      data-reveal={variant}
      data-shown={shown ? "" : undefined}
      style={delay ? { transitionDelay: `${delay}ms` } : undefined}
      className={className}
    >
      {children}
    </div>
  );
}
