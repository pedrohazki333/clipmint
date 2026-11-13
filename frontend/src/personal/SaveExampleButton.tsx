"use client";

import { useState } from "react";

import ValidateModal from "@/components/ValidateModal";
import { buttonClass } from "@/components/ui/editorial";

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
        className={buttonClass("quiet")}
      >
        Salvar exemplo
      </button>
      {aberto && <ValidateModal clipId={clipId} onClose={() => setAberto(false)} />}
    </>
  );
}
