/**
 * Os padrões de marca — o que o clipe usa enquanto ninguém configurou nada.
 *
 * ESPELHO de `backend/app/services/layout.py`. As duas cópias existem porque o
 * preview desenha na tela o que o FFmpeg vai desenhar no vídeo: divergirem faz
 * a tela mentir sobre o clipe. `backend/tests/test_branding_defaults.py`
 * compara os dois.
 *
 * São as cores do produto (as mesmas de `globals.css`), e não a identidade de
 * ninguém: quem usa troca por conta no painel de Marca do perfil.
 */

/** Faixa que separa facecam de gameplay (streamer) ou fecha o banner (podcast). */
export const BAR_DEFAULT_BG = "#121714";
export const BAR_DEFAULT_TEXT = "#34D399";
/**
 * O @ escrito na faixa quando ninguém configurou o seu.
 *
 * Já foi vazio, e aí o modo streamer caía no nome do canal do VÍDEO DE ORIGEM —
 * o clipe saía assinado por quem gravou, não por quem publica.
 */
export const BAR_DEFAULT_NAME = "@suaconta";

/** Banner de título — a pílula sobre a capa. */
export const BANNER_DEFAULT_BG = "#34D399";
export const BANNER_DEFAULT_TEXT = "#0B0F0D";
