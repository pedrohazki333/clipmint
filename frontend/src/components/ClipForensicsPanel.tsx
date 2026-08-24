import type { ClipForensics } from "@/lib/types";

/**
 * A perícia de um clipe standalone.
 *
 * A ordem dos blocos é a ordem em que as perguntas importam: o gancho primeiro
 * (é onde o clipe é ganho ou perdido), depois a estrutura, depois o que cada
 * camada — som, imagem, texto na tela — está fazendo, e só no fim as lições.
 *
 * As regras de corte e as notas de montagem aparecem separadas porque foram
 * geradas separadas, e por um motivo: o analisador do ClipMint escolhe
 * INTERVALOS num vídeo longo. Ele não monta. Misturar as duas listas na tela
 * convidaria a cobrar dele algo que não está ao alcance dele.
 */

function Section({
  title,
  children,
}: {
  title: string;
  children: React.ReactNode;
}) {
  return (
    <div>
      <p className="text-xs text-gray-500 mb-1">{title}</p>
      {children}
    </div>
  );
}

function Prose({ text }: { text: string }) {
  return <p className="text-sm text-gray-300 leading-relaxed">{text}</p>;
}

function Bullets({ items, tone = "gray" }: { items: string[]; tone?: "gray" | "emerald" }) {
  return (
    <ul className="flex flex-col gap-1.5">
      {items.map((item, i) => (
        <li key={i} className="text-sm text-gray-300 leading-relaxed flex gap-2">
          <span className={tone === "emerald" ? "text-emerald-500" : "text-gray-600"}>—</span>
          <span>{item}</span>
        </li>
      ))}
    </ul>
  );
}

const ROLE_COLOR: Record<string, string> = {
  setup: "bg-gray-800 border-gray-700 text-gray-400",
  escalada: "bg-amber-900/30 border-amber-800/60 text-amber-400",
  virada: "bg-fuchsia-900/30 border-fuchsia-800/60 text-fuchsia-400",
  payoff: "bg-emerald-900/30 border-emerald-800/60 text-emerald-400",
  arremate: "bg-sky-900/30 border-sky-800/60 text-sky-400",
};

function list(value: string[] | null | undefined): string[] {
  return (value ?? []).map((v) => String(v).trim()).filter(Boolean);
}

export default function ClipForensicsPanel({ forensics }: { forensics: ClipForensics }) {
  const f = forensics;
  const hook = f.hook_breakdown;
  const beats = f.beats ?? [];
  const retention = list(f.retention_devices);
  const rules = list(f.transferable_rules);
  const production = list(f.production_notes);
  const doNotCopy = list(f.do_not_copy);
  const gaps = list(f.evidence_gaps);

  return (
    <div className="flex flex-col gap-6">
      {/* Gancho */}
      {hook && (
        <div className="rounded-2xl bg-gray-900 border border-gray-800 p-6 flex flex-col gap-4">
          <h2 className="text-base font-semibold text-gray-100">
            Os primeiros segundos
            {hook.seconds_to_promise != null && (
              <span className="ml-2 text-xs font-normal text-gray-500">
                promessa fechada em {hook.seconds_to_promise.toFixed(1)}s
              </span>
            )}
          </h2>

          {hook.on_screen_text && (
            <div className="rounded-lg bg-black/40 border border-gray-800 px-4 py-3">
              <p className="text-xs text-gray-500 mb-1">Texto queimado na tela</p>
              <p className="text-base font-bold text-gray-100 leading-snug">
                {hook.on_screen_text}
              </p>
            </div>
          )}

          <div className="grid gap-4 sm:grid-cols-2">
            {hook.first_frame && (
              <Section title="Primeiro quadro">
                <Prose text={hook.first_frame} />
              </Section>
            )}
            {hook.first_line && (
              <Section title="Primeira fala">
                <p className="text-sm text-gray-300 italic leading-relaxed">
                  “{hook.first_line}”
                </p>
              </Section>
            )}
          </div>

          {hook.mechanism && (
            <Section title="Por que segura">
              <Prose text={hook.mechanism} />
            </Section>
          )}
        </div>
      )}

      {/* Estrutura */}
      {beats.length > 0 && (
        <div className="rounded-2xl bg-gray-900 border border-gray-800 p-6 flex flex-col gap-3">
          <h2 className="text-base font-semibold text-gray-100">Como o clipe é montado</h2>
          <div className="flex flex-col gap-2">
            {beats.map((beat, i) => (
              <div key={i} className="flex gap-3 items-start">
                <span className="text-xs text-gray-600 font-mono pt-1 w-20 flex-shrink-0 tabular-nums">
                  {beat.start?.toFixed(1)}–{beat.end?.toFixed(1)}s
                </span>
                <span
                  className={`text-xs rounded-full border px-2 py-0.5 flex-shrink-0 ${
                    ROLE_COLOR[beat.role] ?? ROLE_COLOR.setup
                  }`}
                >
                  {beat.role}
                </span>
                <span className="text-sm text-gray-300 leading-relaxed">{beat.what}</span>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* As camadas */}
      <div className="rounded-2xl bg-gray-900 border border-gray-800 p-6 grid gap-5 sm:grid-cols-2">
        {f.audio_role && (
          <Section title="O que o som faz">
            <Prose text={f.audio_role} />
          </Section>
        )}
        {f.visual_style && (
          <Section title="O que a imagem faz">
            <Prose text={f.visual_style} />
          </Section>
        )}
        {f.text_strategy && (
          <Section title="O texto na tela">
            <Prose text={f.text_strategy} />
          </Section>
        )}
        {f.edit_rhythm && (
          <Section title="Ritmo de corte">
            <Prose text={f.edit_rhythm} />
          </Section>
        )}
        {f.ending && (
          <Section title="Como termina">
            <Prose text={f.ending} />
          </Section>
        )}
        {f.share_trigger && (
          <Section title="Por que alguém compartilha">
            <Prose text={f.share_trigger} />
          </Section>
        )}
        {f.comment_bait && (
          <Section title="O que provoca comentário">
            <Prose text={f.comment_bait} />
          </Section>
        )}
        {retention.length > 0 && (
          <Section title="O que segura até o fim">
            <Bullets items={retention} />
          </Section>
        )}
      </div>

      {/* O que isso ensina */}
      {(rules.length > 0 || production.length > 0 || doNotCopy.length > 0) && (
        <div className="rounded-2xl bg-gray-900 border border-gray-800 p-6 flex flex-col gap-5">
          <h2 className="text-base font-semibold text-gray-100">O que isso ensina</h2>

          {rules.length > 0 && (
            <Section title="Regras de corte — entram no prompt ao confirmar">
              <Bullets items={rules} tone="emerald" />
            </Section>
          )}
          {production.length > 0 && (
            <Section title="Montagem — para você aplicar na hora de editar">
              <Bullets items={production} />
            </Section>
          )}
          {doNotCopy.length > 0 && (
            <Section title="Não copiar — é específico deste clipe">
              <Bullets items={doNotCopy} />
            </Section>
          )}
        </div>
      )}

      {gaps.length > 0 && (
        <div className="rounded-xl bg-amber-900/15 border border-amber-900/40 px-4 py-3">
          <p className="text-xs text-amber-500/90 mb-1.5">
            O que as evidências não permitiram concluir
          </p>
          <ul className="flex flex-col gap-1">
            {gaps.map((gap, i) => (
              <li key={i} className="text-xs text-amber-200/70 leading-relaxed">
                {gap}
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}
