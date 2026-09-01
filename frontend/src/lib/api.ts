import axios from "axios";
import type {
  AccountUsage,
  AccountUser,
  Balance,
  Catalog,
  Estimate,
  LedgerEntry,
  CostConfig,
  OverviewComparado,
  PaymentAdmin,
  PaymentStatus,
  SerieDia,
  Subscription,
  SubscriptionAdmin,
  Topup,
  UsuarioNoPeriodo,
  Job,
  JobDetail,
  Clip,
  CreateJobPayload,
  FacecamRect,
  SourceType,
  Profile,
  ProfilePayload,
} from "./types";

/** Extrai uma mensagem legível de um erro de API (detail do FastAPI ou fallback). */
export function getApiErrorMessage(err: unknown, fallback: string): string {
  if (axios.isAxiosError(err)) {
    const detail = err.response?.data?.detail;
    if (typeof detail === "string") return detail;
    // Erros de validação do FastAPI vêm como lista de {msg, loc, ...}
    if (Array.isArray(detail) && detail[0]?.msg) return detail[0].msg;
  }
  return fallback;
}

/** Exportada para os módulos de @/personal reusarem a mesma instância. */
export const api = axios.create({
  baseURL: "/api",
  headers: { "Content-Type": "application/json" },
});

// ─── Perfis ──────────────────────────────────────────────────────────────────

export async function listProfiles(): Promise<Profile[]> {
  const { data } = await api.get<Profile[]>("/profiles");
  return data;
}

export async function getProfile(id: string): Promise<Profile> {
  const { data } = await api.get<Profile>(`/profiles/${id}`);
  return data;
}

export async function createProfile(payload: ProfilePayload): Promise<Profile> {
  const { data } = await api.post<Profile>("/profiles", payload);
  return data;
}

export async function updateProfile(
  id: string,
  payload: ProfilePayload,
): Promise<Profile> {
  const { data } = await api.put<Profile>(`/profiles/${id}`, payload);
  return data;
}

/**
 * Congela a caixa da facecam do perfil — ou a solta, com `null`.
 *
 * Rota própria porque `updateProfile` reescreve o perfil inteiro: fixar a caixa
 * a partir da tela de um job teria que reenviar nome, rubrica e defaults, e
 * sobrescreveria com dado velho uma edição feita noutra aba.
 */
export async function pinProfileFacecam(
  id: string,
  rect: FacecamRect | null,
): Promise<Profile> {
  const { data } = await api.put<Profile>(`/profiles/${id}/facecam`, {
    facecam_rect: rect,
  });
  return data;
}

export async function deleteProfile(id: string): Promise<void> {
  await api.delete(`/profiles/${id}`);
}

export async function createJob(payload: CreateJobPayload): Promise<Job> {
  const { data } = await api.post<Job>("/jobs", payload);
  return data;
}

/**
 * Os jobs do usuário.
 *
 * `profileId` é o filtro da nova organização; `source` é o filtro por nicho,
 * que continua existindo porque é como os jobs anteriores aos perfis seguem
 * alcançáveis — eles não têm perfil.
 */
export async function listJobs(params?: {
  profileId?: string;
  source?: SourceType;
}): Promise<Job[]> {
  const { data } = await api.get<Job[]>("/jobs", {
    params: {
      ...(params?.profileId ? { profile_id: params.profileId } : {}),
      ...(params?.source ? { source: params.source } : {}),
    },
  });
  return data;
}

export async function getJob(jobId: string): Promise<JobDetail> {
  const { data } = await api.get<JobDetail>(`/jobs/${jobId}`);
  return data;
}

export async function deleteJob(jobId: string): Promise<void> {
  await api.delete(`/jobs/${jobId}`);
}

/**
 * Retoma um job interrompido/falho reaproveitando download, transcrição,
 * análise e clips já renderizados — só o que falta é refeito.
 */
export async function retryJob(jobId: string): Promise<Job> {
  const { data } = await api.post<Job>(`/jobs/${jobId}/retry`);
  return data;
}

export async function getClip(clipId: string): Promise<Clip> {
  const { data } = await api.get<Clip>(`/clips/${clipId}`);
  return data;
}

export function getDownloadUrl(clipId: string): string {
  return `/api/clips/${clipId}/download`;
}

/**
 * Presets de marca — duas escalas.
 *
 * `profileId` presente: os presets daquele PERFIL, que são do usuário. Ausente:
 * os do NICHO, compartilhados pela instalação e restritos a quem administra.
 *
 * A leitura cai no nicho quando o perfil não tem o arquivo; a escrita nunca cai
 * (senão salvar a marca de um perfil sobrescreveria a de todo mundo).
 */
type Escopo = { source: SourceType; profileId?: string };

function scopeParams({ source, profileId }: Escopo) {
  return profileId ? { source, profile_id: profileId } : { source };
}

export async function uploadWatermark(escopo: Escopo, file: File): Promise<void> {
  const form = new FormData();
  form.append("file", file);
  await api.post("/settings/watermark", form, {
    params: scopeParams(escopo),
    headers: { "Content-Type": "multipart/form-data" },
  });
}

export async function deleteWatermark(escopo: Escopo): Promise<void> {
  await api.delete("/settings/watermark", { params: scopeParams(escopo) });
}

export async function hasWatermark(escopo: Escopo): Promise<boolean> {
  try {
    await api.get("/settings/watermark", {
      params: scopeParams(escopo),
      responseType: "blob",
    });
    return true;
  } catch {
    // 404 = nenhuma marca configurada. É resposta, não falha.
    return false;
  }
}

/** URL da imagem para o <img>. `version` fura o cache depois de um upload. */
export function getWatermarkUrl(escopo: Escopo, version?: number): string {
  const q = new URLSearchParams({ source: escopo.source });
  if (escopo.profileId) q.set("profile_id", escopo.profileId);
  if (version) q.set("v", String(version));
  return `/api/settings/watermark?${q}`;
}

export async function uploadClipWatermark(escopo: Escopo, file: File): Promise<void> {
  const form = new FormData();
  form.append("file", file);
  await api.post("/settings/clip-watermark", form, {
    params: scopeParams(escopo),
    headers: { "Content-Type": "multipart/form-data" },
  });
}

export async function deleteClipWatermark(escopo: Escopo): Promise<void> {
  await api.delete("/settings/clip-watermark", { params: scopeParams(escopo) });
}

export async function hasClipWatermark(escopo: Escopo): Promise<boolean> {
  try {
    await api.get("/settings/clip-watermark", {
      params: scopeParams(escopo),
      responseType: "blob",
    });
    return true;
  } catch {
    return false;
  }
}

export function getClipWatermarkUrl(escopo: Escopo, version?: number): string {
  const q = new URLSearchParams({ source: escopo.source });
  if (escopo.profileId) q.set("profile_id", escopo.profileId);
  if (version) q.set("v", String(version));
  return `/api/settings/clip-watermark?${q}`;
}

export interface BannerColors {
  bg_color: string;
  text_color: string;
  font: string;
  customized: boolean;
  available_fonts: { key: string; label: string }[];
}

export async function getBannerColors(escopo: Escopo): Promise<BannerColors> {
  const { data } = await api.get<BannerColors>("/settings/banner-colors", {
    params: scopeParams(escopo),
  });
  return data;
}

export async function saveBannerColors(
  escopo: Escopo,
  bg_color: string,
  text_color: string,
  font: string,
): Promise<BannerColors> {
  const { data } = await api.put<BannerColors>(
    "/settings/banner-colors",
    { bg_color, text_color, font },
    { params: scopeParams(escopo) },
  );
  return data;
}

export async function resetBannerColors(escopo: Escopo): Promise<void> {
  await api.delete("/settings/banner-colors", { params: scopeParams(escopo) });
}

/** O estilo da faixa que separa facecam de gameplay no modo streamer. */
export interface BarStyle {
  bg_color: string;
  text_color: string;
  font: string;
  /** Nome escrito na faixa. Vazio: o padrão (@suaconta) no streamer, nada no podcast. */
  name: string;
  customized: boolean;
  /** Famílias instaladas na máquina do backend — a lista vem de lá. */
  available_fonts: { key: string; label: string }[];
}

export async function getBarStyle(escopo: Escopo): Promise<BarStyle> {
  const { data } = await api.get<BarStyle>("/settings/bar-style", {
    params: scopeParams(escopo),
  });
  return data;
}

export async function saveBarStyle(
  escopo: Escopo,
  bg_color: string,
  text_color: string,
  font: string,
  name: string,
): Promise<BarStyle> {
  const { data } = await api.put<BarStyle>(
    "/settings/bar-style",
    { bg_color, text_color, font, name },
    { params: scopeParams(escopo) },
  );
  return data;
}

export async function resetBarStyle(escopo: Escopo): Promise<void> {
  await api.delete("/settings/bar-style", { params: scopeParams(escopo) });
}

// ─── Referências (aprender com clipe viral de outro criador) ──────────────────

// ─── Conta (build público) ────────────────────────────────────────────────────

/** Quem está logado, ou null. Não é erro não haver ninguém. */
export async function getMe(): Promise<AccountUser | null> {
  const { data } = await api.get<AccountUser | null>("/auth/me");
  return data;
}

/** Quanto da janela de cota já foi usado. Exige sessão. */
export async function getUsage(): Promise<AccountUsage> {
  const { data } = await api.get<AccountUsage>("/auth/me/usage");
  return data;
}

/** Derruba TODAS as sessões desta conta — inclusive as de outros aparelhos. */
export async function logoutAll(): Promise<number> {
  const { data } = await api.post<{ sessoes_encerradas: number }>(
    "/auth/logout-all",
  );
  return data.sessoes_encerradas;
}

// ─── Cobrança ────────────────────────────────────────────────────────────────

export async function getBalance(): Promise<Balance> {
  const { data } = await api.get<Balance>("/billing/balance");
  return data;
}

export async function getCatalog(): Promise<Catalog> {
  const { data } = await api.get<Catalog>("/billing/catalog");
  return data;
}

export async function getLedger(limit = 50, offset = 0): Promise<LedgerEntry[]> {
  const { data } = await api.get<LedgerEntry[]>("/billing/ledger", {
    params: { limit, offset },
  });
  return data;
}

/**
 * Quanto este vídeo vai custar, antes de gastar qualquer coisa.
 *
 * Levanta os MESMOS 422 da criação do job (live, vídeo acima do teto): é assim
 * que a tela descobre cedo o que o servidor recusaria depois.
 */
export async function estimateJob(youtube_url: string): Promise<Estimate> {
  const { data } = await api.post<Estimate>("/billing/estimate", { youtube_url });
  return data;
}

export async function createTopup(creditos: number): Promise<Topup> {
  const { data } = await api.post<Topup>("/billing/topup", { creditos });
  return data;
}

/** Consulta o pagamento — e sincroniza com o gateway, então serve de polling. */
export async function getPaymentStatus(id: string): Promise<PaymentStatus> {
  const { data } = await api.get<PaymentStatus>(`/billing/payments/${id}`);
  return data;
}

/** Cria a assinatura e devolve o link do gateway onde o cartão é autorizado. */
export async function subscribe(plan_code: string): Promise<Subscription> {
  const { data } = await api.post<Subscription>("/billing/subscribe", { plan_code });
  return data;
}

/** A assinatura viva, ou null. Sincroniza com o gateway quando está pendente. */
export async function getSubscription(): Promise<Subscription | null> {
  const { data } = await api.get<Subscription | null>("/billing/subscription");
  return data;
}

export async function cancelSubscription(): Promise<Subscription> {
  const { data } = await api.post<Subscription>("/billing/subscription/cancel");
  return data;
}

// ─── Painel do dono ──────────────────────────────────────────────────────────
//
// Todas fechadas por `require_owner` no backend. Um usuário comum que chame
// estas funções recebe 403 do servidor — a interface não é a fechadura.

export async function getAdminOverview(mes?: string): Promise<OverviewComparado> {
  const { data } = await api.get<OverviewComparado>("/admin/overview", {
    params: mes ? { mes } : undefined,
  });
  return data;
}

export async function getAdminSeries(mes?: string): Promise<SerieDia[]> {
  const { data } = await api.get<SerieDia[]>("/admin/series", {
    params: mes ? { mes } : undefined,
  });
  return data;
}

export async function getAdminUsers(mes?: string): Promise<UsuarioNoPeriodo[]> {
  const { data } = await api.get<UsuarioNoPeriodo[]>("/admin/users", {
    params: mes ? { mes } : undefined,
  });
  return data;
}

export async function getCostConfig(): Promise<CostConfig> {
  const { data } = await api.get<CostConfig>("/admin/cost-config");
  return data;
}

export async function updateCostConfig(
  campos: Partial<Record<string, string>>,
): Promise<CostConfig> {
  const { data } = await api.put<CostConfig>("/admin/cost-config", campos);
  return data;
}

export async function getAdminPayments(): Promise<PaymentAdmin[]> {
  const { data } = await api.get<PaymentAdmin[]>("/admin/payments");
  return data;
}

export async function createManualPayment(corpo: {
  email: string;
  valor_brl: string;
  taxa_brl?: string;
  referencia?: string;
  pago_em?: string;
  conceder_creditos?: boolean;
  creditos?: number;
}): Promise<PaymentAdmin> {
  const { data } = await api.post<PaymentAdmin>("/admin/payments", corpo);
  return data;
}

export async function setPaymentStatus(
  id: string,
  status: "paid" | "refunded" | "chargeback",
): Promise<PaymentAdmin> {
  const { data } = await api.patch<PaymentAdmin>(`/admin/payments/${id}`, { status });
  return data;
}

export async function createManualSubscription(corpo: {
  email: string;
  plan_code: string;
  valor_brl: string;
  creditos_mes: number;
}): Promise<SubscriptionAdmin> {
  const { data } = await api.post<SubscriptionAdmin>("/admin/subscriptions", corpo);
  return data;
}
