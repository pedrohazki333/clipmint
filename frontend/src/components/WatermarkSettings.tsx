"use client";

import { useEffect, useMemo, useRef } from "react";

import { LinkButton } from "@/components/ui";
import type { FileSlot } from "@/lib/brand";

/**
 * A logo que cobre QR code e assina a capa.
 *
 * Campo CONTROLADO: não fala com a API. Quem grava é o `applyBrandDraft` do
 * formulário, no submit — é isso que permite configurar a marca já na criação
 * do perfil, antes de existir um id para nomear a pasta dos presets.
 *
 * Título e legenda em cima, miniatura e botões numa linha embaixo. Enquanto o
 * texto e os botões dividiam a mesma linha, num celular estreito o bloco
 * quebrava com "Remover" sozinho numa terceira linha, longe da imagem a que se
 * referia — perto o bastante do bloco seguinte para parecer dele.
 */
interface Props {
  value: FileSlot;
  onChange: (v: FileSlot) => void;
  /** Imagem já gravada. Só existe na edição. */
  savedUrl?: string;
  disabled?: boolean;
}

export default function WatermarkSettings({
  value,
  onChange,
  savedUrl,
  disabled = false,
}: Props) {
  const inputRef = useRef<HTMLInputElement>(null);

  // A prévia do arquivo escolhido vive só no navegador até o submit.
  const localUrl = useMemo(
    () => (value.file ? URL.createObjectURL(value.file) : null),
    [value.file],
  );
  useEffect(() => {
    return () => {
      if (localUrl) URL.revokeObjectURL(localUrl);
    };
  }, [localUrl]);

  const mostrando = localUrl ?? (value.saved && !value.remove ? savedUrl : null);

  return (
    <div className="flex flex-col gap-3">
      <div>
        <p className="text-body font-medium text-ink">Marca d&apos;água</p>
        <p className="mt-0.5 text-label leading-relaxed text-ink-muted">
          Sua logo cobre QR codes e marcas de terceiros nos clipes, e assina a
          capa.
        </p>
      </div>

      <div className="flex items-center gap-3">
        {mostrando ? (
          // eslint-disable-next-line @next/next/no-img-element
          <img
            src={mostrando}
            alt="Marca d'água"
            className="h-14 w-14 flex-shrink-0 rounded-sm border border-line bg-inset object-contain p-1.5"
          />
        ) : (
          // Exemplo apagado: nada desta imagem entra no clipe.
          // eslint-disable-next-line @next/next/no-img-element
          <img
            src="/marca-clipmint.png"
            alt="Exemplo de marca d'água"
            title="Exemplo — envie a sua para substituir"
            className="h-14 w-14 flex-shrink-0 rounded-sm border border-dashed border-line bg-inset object-contain p-1.5 opacity-40"
          />
        )}

        <div className="flex flex-wrap items-center gap-x-4 gap-y-2">
          <label
            className={`cursor-pointer rounded-sm border border-line bg-inset px-4 py-2 text-body text-ink transition-colors hover:bg-hover ${
              disabled ? "pointer-events-none opacity-50" : ""
            }`}
          >
            {value.saved || value.file ? "Trocar logo" : "Enviar logo"}
            <input
              ref={inputRef}
              type="file"
              accept="image/png,image/jpeg,image/webp"
              className="hidden"
              disabled={disabled}
              onChange={(e) => {
                const file = e.target.files?.[0];
                if (file) onChange({ ...value, file, remove: false });
                if (inputRef.current) inputRef.current.value = "";
              }}
            />
          </label>
          {(value.file || (value.saved && !value.remove)) && (
            <LinkButton
              disabled={disabled}
              onClick={() => onChange({ ...value, file: null, remove: true })}
              className="hover:text-danger"
            >
              Remover
            </LinkButton>
          )}
        </div>
      </div>

      {value.remove && value.saved && (
        <p className="flex items-center gap-3 rounded-sm bg-inset px-3 py-2 text-label text-ink-dim">
          A logo sai ao salvar.
          <button
            type="button"
            onClick={() => onChange({ ...value, remove: false })}
            className="text-mint transition-colors hover:text-mint-strong"
          >
            Desfazer
          </button>
        </p>
      )}
      {value.file && (
        <p className="rounded-sm bg-inset px-3 py-2 text-label text-ink-dim">
          {value.file.name} — enviada ao salvar.
        </p>
      )}
    </div>
  );
}
