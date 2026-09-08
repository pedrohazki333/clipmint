"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";

import { INVALID_YOUTUBE_URL_MESSAGE, isValidYouTubeUrl } from "@/lib/youtube";
import { ROTA_CADASTRO } from "@/lib/rotas";

/**
 * O campo de link do hero.
 *
 * A pessoa cola a URL antes de ter conta. O link viaja com ela para o cadastro
 * (`?url=`) e chega preenchido na primeira geração — ela digita o endereço uma
 * vez só. Um campo que joga fora o que foi digitado seria pior que não ter
 * campo nenhum: pede trabalho e devolve nada.
 *
 * A validação é a MESMA do produto (`isValidYouTubeUrl`, espelhada no backend),
 * e não uma regex nova escrita para a landing. Um link recusado aqui e aceito
 * lá dentro — ou o contrário — seria uma porta que mente.
 */
export default function HeroUrlForm() {
  const router = useRouter();
  const [url, setUrl] = useState("");
  const [erro, setErro] = useState("");

  function enviar(e: React.FormEvent) {
    e.preventDefault();
    const limpo = url.trim();

    // Campo vazio não é erro: é alguém que quer só criar a conta.
    if (!limpo) {
      router.push(ROTA_CADASTRO);
      return;
    }
    if (!isValidYouTubeUrl(limpo)) {
      setErro(INVALID_YOUTUBE_URL_MESSAGE);
      return;
    }
    router.push(`${ROTA_CADASTRO}&url=${encodeURIComponent(limpo)}`);
  }

  return (
    <div className="w-full">
      <form
        onSubmit={enviar}
        // Pílula única no desktop; no celular o campo e o botão se separam em
        // dois alvos de toque cheios. Espremer os dois numa pílula de 320px dá
        // um input de 140px, onde não cabe uma URL do YouTube.
        className="flex w-full flex-col gap-2 sm:flex-row sm:items-center sm:gap-0 sm:rounded-full sm:border sm:border-line sm:bg-raised sm:p-1.5"
      >
        <label htmlFor="hero-url" className="sr-only">
          Link de um vídeo do YouTube
        </label>
        <input
          id="hero-url"
          type="url"
          inputMode="url"
          autoComplete="off"
          value={url}
          onChange={(e) => {
            setUrl(e.target.value);
            if (erro) setErro("");
          }}
          placeholder="Cole o link de um vídeo do YouTube"
          aria-invalid={erro ? true : undefined}
          aria-describedby={erro ? "hero-url-erro" : undefined}
          className="min-w-0 flex-1 rounded-sm border border-line bg-raised px-5 py-3.5 text-body text-ink placeholder-ink-dim outline-none focus:border-mint sm:rounded-full sm:border-0 sm:bg-transparent sm:py-2.5 sm:focus:border-0"
        />
        <button
          type="submit"
          className="flex-shrink-0 rounded-sm bg-mint-strong px-6 py-3.5 text-body font-semibold text-on-mint transition-colors hover:bg-mint sm:rounded-full sm:py-2.5"
        >
          Começar grátis
        </button>
      </form>

      {erro && (
        <p id="hero-url-erro" role="alert" className="mt-2 text-body text-danger">
          {erro}
        </p>
      )}
    </div>
  );
}
