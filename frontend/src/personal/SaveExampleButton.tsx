"use client";

import { useState } from "react";

import ValidateModal from "@/components/ValidateModal";

/**
 * "Salvar exemplo" — só da versão pessoal.
 *
 * Guarda o clipe como exemplo few-shot em
 * `prompt_engine/examples/validated/`, uma pasta ÚNICA que o PromptBuilder
 * injeta na análise de TODO job. No build público isso faria o aprendizado de um
 * usuário mudar o corte dos outros, incluindo os do dono da instalação — o mesmo
 * vazamento de estado compartilhado que os presets de marca tinham antes de
 * virarem por perfil.
 *
 * Por isso o botão vive aqui e não em `ClipCard`: no público o componente nem é
 * resolvido, e o card simplesmente não o renderiza.
 */
export default function SaveExampleButton({ clipId }: { clipId: string }) {
  const [aberto, setAberto] = useState(false);

  return (
    <>
      <button
        onClick={() => setAberto(true)}
        title="Guardar como exemplo para o aprendizado da análise"
        className="rounded-sm border border-line bg-inset px-3 py-2 text-body text-ink-dim transition-colors hover:border-line-strong hover:text-ink"
      >
        Salvar exemplo
      </button>
      {aberto && <ValidateModal clipId={clipId} onClose={() => setAberto(false)} />}
    </>
  );
}
