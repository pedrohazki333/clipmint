/**
 * Tipos da aba Melhorar vídeo — só existe na versão pessoal.
 *
 * Ficam aqui, e não em lib/types.ts, para o build público não carregar sequer a
 * descrição de uma feature que ele não tem. (Tipo é apagado na compilação, mas
 * manter a fronteira num lugar só evita que a próxima pessoa reintroduza o
 * acoplamento sem perceber.)
 */

export type VideoEnhanceStatus = "pending" | "processing" | "done" | "failed";

export interface VideoEnhanceJob {
  id: string;
  original_filename: string | null;
  status: VideoEnhanceStatus;
  /** Etapa atual ("fazendo upscale"). Só vem durante o trabalho. */
  status_detail: string | null;
  /**
   * Em `failed`, o motivo. Em `done`, o aviso das etapas que falharam — o vídeo
   * existe do mesmo jeito.
   */
  error_message: string | null;
  /** Antes/depois em texto, ex.: "720x1280 · 24fps · 1.9 Mbps". */
  source_summary: string | null;
  final_summary: string | null;
  steps_applied: string[];
  /** Dispensadas por já estarem no alvo — não são problema. */
  steps_skipped: string[];
  has_video: boolean;
  created_at: string;
  updated_at: string;
}
