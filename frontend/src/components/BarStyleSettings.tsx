"use client";

import { useEffect, useState } from "react";
import {
  getApiErrorMessage,
  getBarStyle,
  resetBarStyle,
  saveBarStyle,
} from "@/lib/api";
import ColorField, { HEX_RE, toFullHex } from "@/components/ColorField";

const DEFAULT_BG = "#101014";
const DEFAULT_TEXT = "#9D9D9F";
const DEFAULT_FONT = "condensed";

/**
 * Aproximação em CSS das fontes que o backend usa no render. O preview serve
 * para julgar peso e proporção; a fonte final é a instalada no servidor.
 */
const FONT_STACKS: Record<string, { family: string; weight: number }> = {
  condensed: { family: "'DejaVu Sans Condensed', 'Arial Narrow', sans-serif", weight: 700 },
  sans: { family: "'DejaVu Sans', Arial, sans-serif", weight: 700 },
  inter: { family: "Inter, system-ui, sans-serif", weight: 700 },
  inter_black: { family: "Inter, system-ui, sans-serif", weight: 900 },
  montserrat: { family: "Montserrat, system-ui, sans-serif", weight: 700 },
  montserrat_black: { family: "Montserrat, system-ui, sans-serif", weight: 900 },
  serif: { family: "'DejaVu Serif', Georgia, serif", weight: 700 },
  mono: { family: "'DejaVu Sans Mono', monospace", weight: 700 },
};

/** Mistura duas cores hex (amount = quanto de fg). Espelha _mix() do backend. */
function mix(fg: string, bg: string, amount: number): string {
  const parse = (h: string) => [1, 3, 5].map((i) => parseInt(h.slice(i, i + 2), 16));
  const [fr, fgn, fb] = parse(fg);
  const [br, bgn, bb] = parse(bg);
  const ch = (f: number, b: number) =>
    Math.round(b + (f - b) * amount).toString(16).padStart(2, "0");
  return `#${ch(fr, br)}${ch(fgn, bgn)}${ch(fb, bb)}`;
}

export default function BarStyleSettings() {
  const [bgColor, setBgColor] = useState(DEFAULT_BG);
  const [textColor, setTextColor] = useState(DEFAULT_TEXT);
  const [font, setFont] = useState(DEFAULT_FONT);
  const [fonts, setFonts] = useState<{ key: string; label: string }[]>([]);
  const [customized, setCustomized] = useState(false);
  const [dirty, setDirty] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [saved, setSaved] = useState(false);

  useEffect(() => {
    getBarStyle()
      .then((s) => {
        setBgColor(s.bg_color);
        setTextColor(s.text_color);
        setFont(s.font);
        setFonts(s.available_fonts);
        setCustomized(s.customized);
      })
      .catch(() => {
        /* backend fora do ar — mantém padrões */
      });
  }, []);

  function touch<T>(setter: (v: T) => void) {
    return (v: T) => {
      setter(v);
      setDirty(true);
      setSaved(false);
    };
  }

  const valid = HEX_RE.test(bgColor) && HEX_RE.test(textColor);

  async function handleSave() {
    setBusy(true);
    setError("");
    try {
      const s = await saveBarStyle(bgColor, textColor, font);
      setBgColor(s.bg_color);
      setTextColor(s.text_color);
      setFont(s.font);
      setCustomized(true);
      setDirty(false);
      setSaved(true);
    } catch (err) {
      setError(getApiErrorMessage(err, "Não foi possível salvar o estilo da faixa."));
    } finally {
      setBusy(false);
    }
  }

  async function handleReset() {
    setBusy(true);
    setError("");
    try {
      await resetBarStyle();
      setBgColor(DEFAULT_BG);
      setTextColor(DEFAULT_TEXT);
      setFont(DEFAULT_FONT);
      setCustomized(false);
      setDirty(false);
      setSaved(false);
    } catch (err) {
      setError(getApiErrorMessage(err, "Não foi possível restaurar o padrão."));
    } finally {
      setBusy(false);
    }
  }

  const previewBg = toFullHex(bgColor, DEFAULT_BG);
  const previewText = toFullHex(textColor, DEFAULT_TEXT);
  const previewDot = mix(previewText, previewBg, 0.45);
  const previewHairline = mix(previewText, previewBg, 0.18);
  const stack = FONT_STACKS[font] ?? FONT_STACKS[DEFAULT_FONT];

  return (
    <div className="rounded-2xl bg-gray-900 border border-gray-800 p-6">
      <div>
        <h2 className="text-base font-semibold text-gray-100">Faixa do modo streamer</h2>
        <p className="text-sm text-gray-500 mt-1">
          A linha entre a facecam e a gameplay, onde o nome do streamer se repete.
        </p>
      </div>

      {/* Preview da faixa em proporção parecida com a do clip */}
      <div
        className="mt-4 overflow-hidden rounded select-none"
        style={{
          backgroundColor: previewBg,
          borderTop: `1px solid ${previewHairline}`,
          borderBottom: `1px solid ${previewHairline}`,
        }}
      >
        <div
          className="flex items-center justify-center gap-6 whitespace-nowrap py-2.5 text-xs"
          style={{
            color: previewText,
            fontFamily: stack.family,
            fontWeight: stack.weight,
            letterSpacing: "0.18em",
          }}
        >
          {Array.from({ length: 5 }).map((_, i) => (
            <span key={i} className="flex items-center gap-6">
              ALANZOKA
              {i < 4 && <span style={{ color: previewDot }}>•</span>}
            </span>
          ))}
        </div>
      </div>

      <div className="mt-4 flex flex-wrap items-center gap-6">
        <ColorField
          label="Fundo"
          value={bgColor}
          onChange={touch(setBgColor)}
          disabled={busy}
          fallback={DEFAULT_BG}
        />
        <ColorField
          label="Fonte"
          value={textColor}
          onChange={touch(setTextColor)}
          disabled={busy}
          fallback={DEFAULT_TEXT}
        />

        <div className="flex items-center gap-2">
          <span className="text-xs text-gray-500">Família</span>
          <select
            value={font}
            disabled={busy || fonts.length === 0}
            onChange={(e) => touch(setFont)(e.target.value)}
            className="rounded-lg bg-gray-800 border border-gray-700 px-2 py-1.5 text-sm text-gray-200 outline-none focus:border-gray-500 disabled:opacity-50"
          >
            {(fonts.length ? fonts : [{ key: DEFAULT_FONT, label: "Padrão" }]).map((f) => (
              <option key={f.key} value={f.key}>
                {f.label}
              </option>
            ))}
          </select>
        </div>

        <div className="flex items-center gap-3 ml-auto">
          {(customized || dirty) && (
            <button
              onClick={handleReset}
              disabled={busy}
              className="text-xs text-gray-500 hover:text-gray-300 transition-colors disabled:opacity-50"
            >
              Restaurar padrão
            </button>
          )}
          <button
            onClick={handleSave}
            disabled={busy || !dirty || !valid}
            className="rounded-lg px-4 py-2 text-sm font-medium transition-colors bg-gray-800 hover:bg-gray-700 border border-gray-700 text-gray-300 disabled:opacity-50 disabled:cursor-not-allowed"
          >
            {busy ? "Salvando..." : saved ? "Salvo ✓" : "Salvar"}
          </button>
        </div>
      </div>

      <p className="mt-3 text-xs text-gray-600">
        Vale para os próximos clips gerados. O preview aproxima a fonte com o que o
        navegador tem — o render usa a fonte instalada no servidor.
      </p>

      {!valid && (
        <p className="mt-3 text-xs text-amber-500/80 bg-amber-900/15 rounded px-3 py-2">
          Use hexadecimal no formato #RRGGBB (ex: #101014).
        </p>
      )}
      {error && (
        <p className="mt-3 text-xs text-red-400 bg-red-900/20 rounded px-3 py-2">{error}</p>
      )}
    </div>
  );
}
