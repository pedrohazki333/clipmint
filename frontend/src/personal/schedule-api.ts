/**
 * Cliente da fila de postagem — só existe na versão pessoal.
 *
 * A grade é fixa e é do dono da instalação: 12 horários por dia, cada um
 * escolhendo o clipe que lidera um eixo da rubrica, distribuídos entre as contas
 * dele. Para um usuário público seria uma tabela de horários que ele não
 * escolheu, apontando para contas que não são dele.
 */

import { api } from "@/lib/api";
import type { SourceType } from "@/lib/types";

export interface ScheduleSlot {
  time: string;
  source_type: SourceType;
  axis: string;
}

export interface SchedulePick {
  clip_id: string;
  job_id: string;
  axis: string;
  axis_score: number | null;
  virality_score: number;
  source_type: SourceType;
  video_title: string | null;
  channel_name: string | null;
  start_time: number;
  end_time: number;
  duration: number;
  hook: string | null;
  suggested_title: string | null;
  verdict: string | null;
  file_path: string | null;
}

export async function listScheduleSlots(): Promise<ScheduleSlot[]> {
  const { data } = await api.get<ScheduleSlot[]>("/schedule/slots");
  return data;
}

export async function pickForSlot(
  axis: string,
  source: SourceType,
  exclude: string[] = []
): Promise<SchedulePick[]> {
  const { data } = await api.get<SchedulePick[]>("/schedule/pick", {
    params: { axis, source, limit: 1, exclude: exclude.join(",") || undefined },
  });
  return data;
}
