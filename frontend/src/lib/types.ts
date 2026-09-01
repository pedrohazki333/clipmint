export type SubtitleMode = "word_highlight" | "traditional" | "none";

/**
 * Como o clipe é montado.
 *
 * `cover` e `streamer` presumem o tipo de conteúdo (rosto falando / câmera
 * separada do jogo) e por isso só valem em certas rubricas; `crop` e `original`
 * não presumem nada. Ver lib/layouts.ts.
 */
export type LayoutMode = "cover" | "streamer" | "crop" | "original";

/**
 * Muda a rubrica da análise e define a conta no cronograma de postagem.
 *
 * "siege" continua na união mesmo no build público: tipo é apagado na
 * compilação, então não alcança o bundle, e tirá-lo daqui obrigaria a duplicar
 * o arquivo por variante. Quem decide os nichos que EXISTEM é a lista de
 * src/lib/features.ts, não este tipo.
 */
export type SourceType = "podcast" | "gameplay" | "siege";

/**
 * "compilation" PEDE um compilado (vários momentos costurados num vídeo só).
 * Não achando material que se sustente, o backend entrega clipes individuais.
 */
export type ClipMode = "individual" | "compilation";

/**
 * O que fazer com os trechos que o usuário indicou à mão.
 * "only" corta apenas eles; "plus" mantém a análise procurando outros além.
 */
export type ManualMode = "only" | "plus";

/** Eixos da rubrica de viralidade, 0–10 cada. */
export const SCORE_AXES = [
  { key: "hook_score", label: "Gancho", hint: "Força nos 3 primeiros segundos" },
  { key: "retention_score", label: "Retenção", hint: "Segura a atenção até o fim" },
  { key: "shareability_score", label: "Compart.", hint: "Eu mandaria isso pra alguém" },
  { key: "comment_bait_score", label: "Comentários", hint: "Gera debate ou reação" },
  { key: "loopability_score", label: "Loop", hint: "O fim reconecta com o início" },
] as const;

/** Caixa da facecam em frações (0–1) da fonte. */
export interface FacecamRect {
  x: number;
  y: number;
  w: number;
  h: number;
  confidence?: number;
  method?: string;
}

export type JobStatus =
  | "queued"
  | "downloading"
  | "transcribing"
  | "analyzing"
  | "clipping"
  | "done"
  | "error";

/**
 * "expired" = o arquivo saiu do disco pelo TTL, mas a linha ficou. A nota, os
 * eixos da rubrica e o desempenho real continuam ali — são eles que alimentam
 * o few-shot, e apagá-los para economizar bytes destruiria o aprendizado.
 */
/** Uma troca de etapa do pipeline, do jeito que o backend registra. */
export interface StageMark {
  /** O status em que o job entrou. */
  s: JobStatus;
  /** Quando, em ISO-8601. */
  at: string;
}

export type ClipStatus = "processing" | "ready" | "error" | "expired";

/**
 * Um perfil: o conjunto de configurações que se repete de vídeo para vídeo.
 *
 * `source_type` é a rubrica BASE — o perfil escolhe entre as que existem, não
 * inventa uma nova. É esse valor que o perfil entrega ao job na criação, e é o
 * job que o guarda: por isso editar um perfil não reescreve análise já feita.
 */
export interface Profile {
  id: string;
  name: string;
  source_type: SourceType;
  /** Chave de ícone, não arquivo (ver AVATARS em lib/avatars.tsx). */
  avatar: string | null;
  default_layout_mode: LayoutMode;
  default_subtitle_mode: SubtitleMode;
  /** Caixa da facecam congelada para este canal. Nula = detectar a cada vídeo. */
  facecam_rect: FacecamRect | null;
  /** Derivadas dos jobs e clipes — nenhum contador é mantido em coluna. */
  job_count: number;
  clip_count: number;
  last_generated_at: string | null;
}

export interface ProfilePayload {
  name: string;
  source_type: SourceType;
  avatar: string | null;
  default_layout_mode: LayoutMode;
  default_subtitle_mode: SubtitleMode;
  /** Omitida, a edição SOLTA a caixa: editar o perfil o reescreve por inteiro. */
  facecam_rect?: FacecamRect | null;
}

export interface Job {
  id: string;
  youtube_url: string;
  /** De qual perfil veio. Nulo nos jobs anteriores aos perfis. */
  profile_id: string | null;
  video_title: string | null;
  channel_name: string | null;
  duration_seconds: number | null;
  thumbnail_url: string | null;
  subtitle_mode: SubtitleMode;
  layout_mode: LayoutMode;
  source_type: SourceType;
  clip_mode: ClipMode;
  facecam_rect: FacecamRect | null;
  status: JobStatus;
  error_message: string | null;
  /** Por que terminou sem clips. Nulo = terminou com clips. */
  result_note: string | null;
  /** Quando cada etapa começou. Nulo = job anterior a este registro. */
  stage_log: StageMark[] | null;
  created_at: string;
  updated_at: string;
}

export interface Clip {
  id: string;
  job_id: string;
  start_time: number;
  end_time: number;
  duration: number;
  virality_score: number;
  /** Nulos em clipes analisados antes da rubrica de cinco eixos. */
  hook_score: number | null;
  retention_score: number | null;
  shareability_score: number | null;
  loopability_score: number | null;
  comment_bait_score: number | null;
  verdict: string | null;
  weak_points_json: string | null;
  trim_reason: string | null;
  /** JSON [[ini,fim],...] quando o clipe foi costurado de vários trechos. */
  segments_json: string | null;
  hook: string | null;
  reason: string | null;
  tags_json: string | null;
  suggested_title: string | null;
  transcript_excerpt: string | null;
  part_number: number | null;
  parent_clip_id: string | null;
  subtitle_mode: SubtitleMode;
  status: ClipStatus;
  file_path: string | null;
  file_size_bytes: number | null;
  created_at: string;
}

export interface JobDetail extends Job {
  clips: Clip[];
  /**
   * Créditos deste job. Nulos na versão pessoal e em jobs anteriores à
   * cobrança — lá não há o que mostrar, e mostrar "0" seria mentira.
   */
  creditos_reservados: number | null;
  creditos_cobrados: number | null;
  saldo: number | null;
}

export interface CreateJobPayload {
  /** De qual perfil parte a geração. Omitido = payload de antes, sem perfil. */
  profile_id?: string;
  youtube_url: string;
  subtitle_mode: SubtitleMode;
  layout_mode?: LayoutMode;
  /** Omitido = inferido do layout (streamer→gameplay, cover→podcast). */
  source_type?: SourceType;
  /** Omitido = "individual" (um clipe por momento, como sempre). */
  clip_mode?: ClipMode;
  /** Trechos indicados à mão, como digitados ("3:24 - 4:10, 12:05 - 12:40"). */
  manual_clips?: string;
  /** Só faz sentido junto de manual_clips. Omitido = "only". */
  manual_mode?: ManualMode;
  /** Só no modo streamer; omitido = detecção automática da webcam. */
  facecam_rect?: FacecamRect;
}

// ─── Referências (aprender com clipe viral de outro criador) ──────────────────

/**
 * Como a referência foi aprendida.
 *
 * "aligned"    — veio com a URL do vídeo original e o corte foi localizado
 *                dentro dele. Sabe o que ficou de fora.
 * "standalone" — só o arquivo do clipe (o caso do TikTok). O clipe é periciado
 *                por si: fala, som, imagem e cortes.
 */
export type ReferenceKind = "aligned" | "standalone";

export type ReferenceStatus =
  | "queued"
  // modo alinhado
  | "downloading_source"
  | "aligning"
  // modo standalone
  | "extracting"
  | "watching"
  // comuns aos dois
  | "transcribing"
  | "analyzing"
  | "done"
  | "error";

export type Performance = "viral" | "muito_bom" | "bom";

export interface ReferenceAnalysis {
  hook: string;
  suggested_title: string;
  virality_score: number;
  reason: string;
  tags: string[];
  why_this_cut: string;
}

export interface ClipBeat {
  start: number;
  end: number;
  role: string;
  what: string;
}

export interface ClipHookBreakdown {
  first_frame?: string | null;
  first_line?: string | null;
  on_screen_text?: string | null;
  mechanism?: string | null;
  seconds_to_promise?: number | null;
}

/** A perícia detalhada de um clipe standalone (backend: forensics_json). */
export interface ClipForensics {
  hook_breakdown?: ClipHookBreakdown | null;
  beats?: ClipBeat[] | null;
  audio_role?: string | null;
  visual_style?: string | null;
  text_strategy?: string | null;
  edit_rhythm?: string | null;
  retention_devices?: string[] | null;
  share_trigger?: string | null;
  comment_bait?: string | null;
  ending?: string | null;
  /** Regras de escolha de corte — o que entra no prompt do analisador. */
  transferable_rules?: string[] | null;
  /** Lições de montagem: verdadeiras sobre o clipe, mas fora do alcance de quem só corta. */
  production_notes?: string[] | null;
  do_not_copy?: string[] | null;
  evidence_gaps?: string[] | null;
}

export interface Reference {
  id: string;
  kind: ReferenceKind;
  source_type: SourceType;
  source_url: string;
  source_title: string | null;
  source_channel: string | null;
  source_duration: number | null;
  language: string | null;
  source_start: number | null;
  source_end: number | null;
  alignment_confidence: number | null;
  clip_duration: number | null;
  analysis: ReferenceAnalysis | null;
  /** Só no modo standalone. */
  forensics: ClipForensics | null;
  opening_phrase: string | null;
  transcript_excerpt: string | null;
  performance: Performance | null;
  views: number | null;
  notas: string | null;
  status: ReferenceStatus;
  error_message: string | null;
  published: boolean;
  example_path: string | null;
  created_at: string;
  updated_at: string;
}

export interface UpdateReferencePayload {
  source_start?: number;
  source_end?: number;
  performance?: Performance;
  views?: number;
  notas?: string;
  reanalyze?: boolean;
}

// ─── Padrões aprendidos (Fase 3) ──────────────────────────────────────────────

export interface LearnedPatterns {
  patterns: string[];
  patterns_text: string;
  generated_at: string | null;
  n_examples: number;
  available_examples: number;
  stats: Record<string, unknown> | null;
  stale: boolean;
}

// ─── Conta (build público) ────────────────────────────────────────────────────

export interface AccountUser {
  id: string;
  email: string;
  display_name: string | null;
  /** Administra esta instalação: só ele altera os presets de marca do nicho. */
  is_owner: boolean;
}

/** Consumo da janela de cota. Teto 0 = sem teto. */
export interface AccountUsage {
  window_hours: number;
  videos_used: number;
  videos_max: number;
  minutes_used: number;
  minutes_max: number;
  /** Duração máxima de UM vídeo, em minutos. 0 = sem teto. */
  max_source_minutes: number;
}


// ─── Cobrança ────────────────────────────────────────────────────────────────

export interface Balance {
  saldo: number;
  /** Abaixo disto a interface avisa. Vem da config do servidor. */
  threshold: number;
  baixo: boolean;
}

export interface Pacote {
  creditos: number;
  /** Já resolvido pelo servidor — a tela nunca calcula preço. */
  preco_brl: string;
}

export interface Plano {
  code: string;
  nome: string;
  valor_brl: string;
  creditos_mes: number;
}

export interface Catalog {
  credito_avulso_brl: string;
  pacotes: Pacote[];
  planos: Plano[];
}

export type LedgerTipo =
  | "topup"
  | "debito"
  | "estorno"
  | "bonus"
  | "ajuste"
  | "hold"
  | "release";

export interface LedgerEntry {
  id: string;
  tipo: LedgerTipo;
  /** Com sinal: positivo credita, negativo debita. */
  amount: number;
  balance_after: number;
  descricao: string | null;
  created_at: string;
  ref_payment_id: string | null;
  ref_usage_id: string | null;
}

export interface Estimate {
  minutos: number;
  creditos: number;
  saldo: number;
  suficiente: boolean;
  /** Quantos faltam. 0 quando dá. */
  faltam: number;
}

export interface Topup {
  payment_id: string;
  creditos: number;
  valor_brl: string;
  status: string;
  qr_code: string | null;
  qr_code_base64: string | null;
  expires_at: string | null;
}

export interface PaymentStatus {
  payment_id: string;
  status: string;
  creditos: number;
  saldo: number;
}

export type SubscriptionStatus = "pending" | "active" | "canceled" | "paused";

export interface Subscription {
  id: string;
  plan_code: string;
  valor_brl: string;
  creditos_mes: number;
  status: SubscriptionStatus;
  /** Link do gateway onde a pessoa autoriza o cartão. Vem com `pending`. */
  init_point: string | null;
  started_at: string | null;
  current_period_end: string | null;
  canceled_at: string | null;
}

// ─── Painel do dono ──────────────────────────────────────────────────────────

export interface Overview {
  periodo: string;
  mrr_brl: string;
  assinantes_ativos: number;
  novos_no_mes: number;
  cancelados_no_mes: number;
  churn_pct: string;
  receita_bruta_brl: string;
  taxas_gateway_brl: string;
  receita_liquida_brl: string;
  pagamentos: number;
  custo_variavel_brl: string;
  custo_fixo_brl: string;
  imposto_brl: string;
  lucro_liquido_brl: string;
  margem_liquida_pct: string;
  /** Custou e não recebeu: job que falhou ou foi excluído em andamento. */
  prejuizo_devolvido_brl: string;
  videos_devolvidos: number;
  videos_processados: number;
  taxas_estimadas: number;
  imposto_pct: string;
  avisos: string[];
}

export interface OverviewComparado {
  atual: Overview;
  anterior: Overview;
}

export interface SerieDia {
  dia: string;
  receita_brl: string;
  custo_brl: string;
  lucro_brl: string;
}

export interface UsuarioNoPeriodo {
  user_id: string;
  email: string;
  receita_brl: string;
  custo_brl: string;
  resultado_brl: string;
  videos: number;
  deficitario: boolean;
}

export interface CostConfig {
  assemblyai_usd_per_min: string;
  llm_rates: Record<string, { input: number; output: number }>;
  storage_usd_per_video: string;
  fx_usd_brl: string;
  fx_eur_brl: string;
  fixed_cost_brl_month: string;
  tax_pct_on_revenue: string;
  gateway_fee_pct: string;
  updated_at: string | null;
}

export interface PaymentAdmin {
  id: string;
  user_id: string;
  gateway: string;
  gateway_payment_id: string;
  tipo: string;
  amount_brl_gross: string;
  gateway_fee_brl: string | null;
  credits_granted: number;
  status: string;
  paid_at: string | null;
  created_at: string | null;
}

export interface SubscriptionAdmin {
  id: string;
  user_id: string;
  plan_code: string;
  valor_brl: string;
  creditos_mes: number;
  status: string;
  gateway: string;
  started_at: string | null;
  canceled_at: string | null;
}
