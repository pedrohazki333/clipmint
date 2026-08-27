"use client";

import { useCallback, useEffect, useState } from "react";

import ReferenceForm from "@/components/ReferenceForm";
import ReferenceCard from "@/components/ReferenceCard";
import LearnedPatterns from "@/components/LearnedPatterns";
import type { Reference } from "@/lib/types";

import { listReferences } from "./learning-api";

/**
 * O bloco de aprendizado da home — só da versão pessoal.
 *
 * Aprender com clipe viral de outro criador, a lista de referências em
 * andamento, e os padrões minerados delas. No build público este arquivo nem é
 * resolvido: quem o importa é `@/personal`, que lá vira um stub.
 *
 * Trouxe a busca das referências junto de propósito. Se ela ficasse na home, a
 * home continuaria chamando `listReferences` e a URL sobreviveria no bundle
 * público como código morto — que é exatamente o que este arranjo evita.
 */

const ACTIVE_POLLING_INTERVAL = 5000; // ms — só enquanto houver leitura rodando
const TERMINAL = new Set(["done", "error"]);

export default function LearningSection() {
  const [references, setReferences] = useState<Reference[]>([]);

  const carregar = useCallback(async () => {
    try {
      setReferences(await listReferences());
    } catch {
      // silencioso — é um painel secundário da home, e o erro real de cada
      // referência aparece na página dela
    }
  }, []);

  useEffect(() => {
    carregar();
  }, [carregar]);

  const rodando = references.some((r) => !TERMINAL.has(r.status));
  useEffect(() => {
    if (!rodando) return;
    const t = setInterval(carregar, ACTIVE_POLLING_INTERVAL);
    return () => clearInterval(t);
  }, [rodando, carregar]);

  return (
    <>
      <ReferenceForm />

      {references.length > 0 && (
        <div>
          <h2 className="mb-4 text-title font-semibold text-ink">Referências</h2>
          <div className="flex flex-col gap-3">
            {references.map((r) => (
              <ReferenceCard key={r.id} reference={r} />
            ))}
          </div>
        </div>
      )}

      <LearnedPatterns />
    </>
  );
}
