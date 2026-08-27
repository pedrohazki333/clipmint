/**
 * Validação do link do YouTube — espelho do backend.
 *
 * ATENÇÃO: este regex tem que ser idêntico ao `_YOUTUBE_URL_RE` de
 * `backend/app/schemas.py`. As duas cópias existirem é o preço de validar nos
 * dois lados (uma em Python, outra em TypeScript); divergirem é bug, e já foi:
 *
 *  - o front recusava `youtube.com/shorts/...` e `youtube.com/live/...` que o
 *    backend aceita, então links válidos morriam na tela com "URL inválida";
 *  - o front aceitava `www.youtube.com/watch?v=x` (sem esquema) e até
 *    `https://evil.com/?redir=youtube.com/watch?v=x`, que o backend recusava
 *    depois do submit com um 422 — erro tardio e feio para um erro de digitação.
 *
 * A causa dos dois era o regex daqui não estar ancorado e não conhecer shorts e
 * live. `backend/tests/test_youtube_url.py` guarda a tabela de casos que os
 * dois lados têm que responder igual; ao mexer aqui, mexa lá também.
 */
const YOUTUBE_URL_RE =
  /^https?:\/\/(www\.|m\.)?(youtube\.com\/(watch\?(\S*&)?v=[\w-]+|shorts\/[\w-]+|live\/[\w-]+)|youtu\.be\/[\w-]+)/;

export function isValidYouTubeUrl(url: string): boolean {
  return YOUTUBE_URL_RE.test(url.trim());
}

/** A mesma frase que o backend devolve, para o erro não mudar de tom. */
export const INVALID_YOUTUBE_URL_MESSAGE =
  "URL inválida: forneça um link do YouTube (youtube.com ou youtu.be).";
