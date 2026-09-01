"use client";

import { useCallback, useEffect, useState } from "react";

import { getApiErrorMessage, getProfile, pinProfileFacecam } from "@/lib/api";
import type { FacecamRect, JobDetail, Profile } from "@/lib/types";

/**
 * Congela, no perfil, a caixa da facecam que ESTE vídeo usou.
 *
 * Detectar a caixa é palpite a cada vídeo, e quando erra o painel sai com
 * gameplay no topo e a cabeça do streamer cortada. O canal é sempre o mesmo e a
 * cam não anda de lugar: depois de conferir que os clipes ficaram bons, o dono
 * congela aquela caixa e o palpite por vídeo vira dado por canal.
 *
 * Fica DEPOIS da grade de clipes de propósito. Fixar antes de olhar o resultado
 * é congelar um erro — o botão só faz sentido para quem já conferiu.
 */

/** Mesma caixa? Fração tem ruído de arredondamento; comparar exato erraria. */
function mesmaCaixa(a: FacecamRect | null, b: FacecamRect | null): boolean {
  if (!a || !b) return false;
  return (
    Math.abs(a.x - b.x) < 1e-4 &&
    Math.abs(a.y - b.y) < 1e-4 &&
    Math.abs(a.w - b.w) < 1e-4 &&
    Math.abs(a.h - b.h) < 1e-4
  );
}

function pct(v: number): string {
  return `${(v * 100).toFixed(1)}%`;
}

export default function FixarFacecam({ job }: { job: JobDetail }) {
  const [perfil, setPerfil] = useState<Profile | null>(null);
  const [salvando, setSalvando] = useState(false);
  const [erro, setErro] = useState("");

  const doJob = job.facecam_rect;
  const aplicavel = job.layout_mode === "streamer" && Boolean(doJob) && Boolean(job.profile_id);

  const carregar = useCallback(() => {
    if (!job.profile_id) return;
    getProfile(job.profile_id)
      .then(setPerfil)
      .catch(() => setPerfil(null));
  }, [job.profile_id]);

  useEffect(() => {
    if (aplicavel) carregar();
  }, [aplicavel, carregar]);

  if (!aplicavel || !perfil || !doJob) return null;

  const fixada = perfil.facecam_rect;
  const ehEsta = mesmaCaixa(fixada, doJob);

  async function aplicar(rect: FacecamRect | null) {
    if (!job.profile_id) return;
    setSalvando(true);
    setErro("");
    try {
      setPerfil(await pinProfileFacecam(job.profile_id, rect));
    } catch (err) {
      setErro(getApiErrorMessage(err, "Não foi possível salvar a caixa no perfil."));
    } finally {
      setSalvando(false);
    }
  }

  return (
    <div className="flex flex-col gap-3 rounded-md border border-line bg-raised p-4 sm:p-6">
      <div>
        <h2 className="text-title font-semibold text-ink">Caixa da facecam</h2>
        <p className="mt-1 text-body text-ink-dim">
          {ehEsta
            ? `Os próximos vídeos de ${perfil.name} vão usar esta caixa, sem detectar.`
            : fixada
              ? `${perfil.name} tem outra caixa fixada. Esta só vale se você substituir.`
              : `Ficaram bons? Congele esta caixa em ${perfil.name} e os próximos vídeos não dependem mais da detecção.`}
        </p>
      </div>

      <p className="font-mono text-label text-ink-muted">
        deste vídeo: x {pct(doJob.x)} · y {pct(doJob.y)} · {pct(doJob.w)} × {pct(doJob.h)}
        {fixada && !ehEsta && (
          <>
            <br />
            no perfil: x {pct(fixada.x)} · y {pct(fixada.y)} · {pct(fixada.w)} ×{" "}
            {pct(fixada.h)}
          </>
        )}
      </p>

      {erro && (
        <p className="rounded-sm border border-danger/40 bg-danger-soft px-3 py-2 text-body text-danger">
          {erro}
        </p>
      )}

      <div className="flex flex-col gap-2 sm:flex-row">
        {!ehEsta && (
          <button
            type="button"
            onClick={() => aplicar(doJob)}
            disabled={salvando}
            className="rounded-sm bg-mint-strong px-5 py-2.5 text-body font-medium text-base transition-colors hover:bg-mint disabled:opacity-50"
          >
            {salvando
              ? "Salvando..."
              : fixada
                ? "Substituir pela caixa deste vídeo"
                : "Fixar esta caixa no perfil"}
          </button>
        )}
        {fixada && (
          <button
            type="button"
            onClick={() => aplicar(null)}
            disabled={salvando}
            className="rounded-sm border border-line px-5 py-2.5 text-body text-ink-dim transition-colors hover:border-line-strong hover:text-ink disabled:opacity-50"
          >
            Voltar a detectar automaticamente
          </button>
        )}
      </div>
    </div>
  );
}
