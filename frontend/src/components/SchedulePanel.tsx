"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import type { SourceType } from "@/lib/types";
import { getApiErrorMessage } from "@/lib/api";
import {
  listScheduleSlots,
  pickForSlot,
  type SchedulePick,
  type ScheduleSlot,
} from "@/personal/schedule-api";

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
  const [error, setError] = useState("");

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const all = await listScheduleSlots();
      const mine = all.filter((s) => s.source_type === source);
      setSlots(mine);
      setError("");

      const used: string[] = [];
      const result: Record<string, SchedulePick | null> = {};
      for (const slot of mine) {
        const [pick] = await pickForSlot(slot.axis, source, used);
        result[slot.time] = pick ?? null;
        if (pick) used.push(pick.clip_id);
      }
      setPicks(result);
    } catch (err) {
      // Antes isto fazia `setSlots([])`, e uma falha de rede ficava idêntica a
      // "nenhum horário na grade": a tela dizia "0 de 0" e ninguém sabia se o
      // problema era o servidor ou a configuração.
      setSlots([]);
      setError(
        getApiErrorMessage(err, "Não foi possível carregar a fila de postagem."),
      );
    } finally {
      setLoading(false);
    }
  }, [source]);

  useEffect(() => {
    load();
  }, [load]);

  const filled = Object.values(picks).filter(Boolean).length;

  return (
    <div className="rounded-md bg-raised border border-line p-6">
      <div className="flex items-center justify-between mb-1">
        <h2 className="text-title font-semibold text-ink">Fila de postagem</h2>
        <button
          onClick={load}
          className="text-label text-ink-dim hover:text-ink transition-colors"
        >
          Atualizar
        </button>
      </div>
      {error ? (
        <p className="mb-4 rounded-sm border border-danger/40 bg-danger-soft px-3 py-2 text-body text-danger">
          {error}
        </p>
      ) : (
        <p className="mb-4 text-body text-ink-dim">
          {loading
            ? "Montando a grade do dia..."
            : `${filled} de ${slots.length} horários com clipe disponível.`}
        </p>
      )}

      {!loading && !error && slots.length === 0 && (
        <p className="text-body text-ink-dim">
          Nenhum horário configurado para esta conta.
        </p>
      )}

      <div className="flex flex-col divide-y divide-line">
        {slots.map((slot) => {
          const pick = picks[slot.time];
          return (
            <div key={slot.time} className="flex items-center gap-4 py-2.5">
              <div className="w-14 flex-shrink-0 font-mono text-body text-ink">
                {slot.time}
              </div>
              <div className="w-32 flex-shrink-0">
                <span className="rounded bg-inset px-2 py-0.5 text-label text-ink-dim">
                  {AXIS_LABEL[slot.axis] ?? slot.axis}
                </span>
              </div>
              <div className="flex-1 min-w-0">
                {pick ? (
                  <Link
                    href={`/jobs/${pick.job_id}`}
                    className="block truncate text-body text-ink hover:text-mint transition-colors"
                  >
                    {pick.suggested_title || pick.hook || "Clipe sem título"}
                  </Link>
                ) : (
                  <span className="text-body text-ink-muted">— sem clipe pontuado neste eixo</span>
                )}
                {pick && (
                  <div className="text-label text-ink-muted truncate">
                    {formatTime(pick.start_time)}–{formatTime(pick.end_time)} ·{" "}
                    {pick.video_title ?? "vídeo"}
                  </div>
                )}
              </div>
              {pick && (
                <div className="flex-shrink-0 text-right">
                  <div className="text-body font-semibold text-mint">
                    {pick.axis_score?.toFixed(1) ?? "–"}
                  </div>
                  <div className="text-[10px] text-ink-muted">no eixo</div>
                </div>
              )}
            </div>
          );
        })}
      </div>

      {!loading && slots.length > 0 && filled === 0 && (
        <p className="mt-4 text-label text-ink-muted">
          Nenhum clipe pontuado ainda. A grade se preenche conforme os vídeos desta conta
          terminam de ser processados.
        </p>
      )}
    </div>
  );
}
