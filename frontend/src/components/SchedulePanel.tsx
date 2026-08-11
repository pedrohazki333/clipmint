"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import type { SourceType } from "@/lib/types";
import {
  listScheduleSlots,
  pickForSlot,
  type SchedulePick,
  type ScheduleSlot,
} from "@/lib/api";

const AXIS_LABEL: Record<string, string> = {
  hook: "Gancho",
  retention: "Retenção",
  shareability: "Compartilhamento",
  comment_bait: "Comentários",
  loopability: "Loop",
  overall: "Equilibrado",
};

function formatTime(seconds: number): string {
  const m = Math.floor(seconds / 60);
  const s = Math.floor(seconds % 60);
  return `${m}:${s.toString().padStart(2, "0")}`;
}

interface Props {
  source: SourceType;
}

/**
 * Grade do dia desta conta: cada horário mostra o clipe que lidera o eixo
 * daquele slot. Um clipe que já apareceu num horário anterior sai da disputa
 * dos seguintes — a grade nunca repete o mesmo vídeo no mesmo dia.
 */
export default function SchedulePanel({ source }: Props) {
  const [slots, setSlots] = useState<ScheduleSlot[]>([]);
  const [picks, setPicks] = useState<Record<string, SchedulePick | null>>({});
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const all = await listScheduleSlots();
      const mine = all.filter((s) => s.source_type === source);
      setSlots(mine);

      const used: string[] = [];
      const result: Record<string, SchedulePick | null> = {};
      for (const slot of mine) {
        const [pick] = await pickForSlot(slot.axis, source, used);
        result[slot.time] = pick ?? null;
        if (pick) used.push(pick.clip_id);
      }
      setPicks(result);
    } catch {
      setSlots([]);
    } finally {
      setLoading(false);
    }
  }, [source]);

  useEffect(() => {
    load();
  }, [load]);

  const filled = Object.values(picks).filter(Boolean).length;

  return (
    <div className="rounded-2xl bg-gray-900 border border-gray-800 p-6">
      <div className="flex items-center justify-between mb-1">
        <h2 className="text-lg font-semibold text-gray-300">Fila de postagem</h2>
        <button
          onClick={load}
          className="text-xs text-gray-500 hover:text-gray-300 transition-colors"
        >
          Atualizar
        </button>
      </div>
      <p className="text-sm text-gray-500 mb-4">
        {loading
          ? "Montando a grade do dia..."
          : `${filled} de ${slots.length} horários com clipe disponível.`}
      </p>

      <div className="flex flex-col divide-y divide-gray-800">
        {slots.map((slot) => {
          const pick = picks[slot.time];
          return (
            <div key={slot.time} className="flex items-center gap-4 py-2.5">
              <div className="w-14 flex-shrink-0 font-mono text-sm text-gray-300">
                {slot.time}
              </div>
              <div className="w-32 flex-shrink-0">
                <span className="rounded bg-gray-800 px-2 py-0.5 text-xs text-gray-400">
                  {AXIS_LABEL[slot.axis] ?? slot.axis}
                </span>
              </div>
              <div className="flex-1 min-w-0">
                {pick ? (
                  <Link
                    href={`/jobs/${pick.job_id}`}
                    className="block truncate text-sm text-gray-200 hover:text-emerald-400 transition-colors"
                  >
                    {pick.suggested_title || pick.hook || "Clipe sem título"}
                  </Link>
                ) : (
                  <span className="text-sm text-gray-600">— sem clipe pontuado neste eixo</span>
                )}
                {pick && (
                  <div className="text-xs text-gray-600 truncate">
                    {formatTime(pick.start_time)}–{formatTime(pick.end_time)} ·{" "}
                    {pick.video_title ?? "vídeo"}
                  </div>
                )}
              </div>
              {pick && (
                <div className="flex-shrink-0 text-right">
                  <div className="text-sm font-semibold text-emerald-400">
                    {pick.axis_score?.toFixed(1) ?? "–"}
                  </div>
                  <div className="text-[10px] text-gray-600">no eixo</div>
                </div>
              )}
            </div>
          );
        })}
      </div>

      {!loading && slots.length > 0 && filled === 0 && (
        <p className="mt-4 text-xs text-gray-600">
          Nenhum clipe pontuado ainda. A grade se preenche conforme os vídeos desta conta
          terminam de ser processados.
        </p>
      )}
    </div>
  );
}
