"use client";
import type { SourceType } from "@/lib/types";

import { useEffect, useState } from "react";
import {
  getApiErrorMessage,
  getBarStyle,
  resetBarStyle,
  saveBarStyle,
} from "@/lib/api";
import ColorField, { HEX_RE, toFullHex } from "@/components/ColorField";
import FontField, { DEFAULT_FONT, fontStack } from "@/components/FontField";

const DEFAULT_BG = "#101014";
const DEFAULT_TEXT = "#9D9D9F";
const MAX_NAME = 40;

/** Mistura duas cores hex (amount = quanto de fg). Espelha _mix() do backend. */
function mix(fg: string, bg: string, amount: number): string {
  const parse = (h: string) => [1, 3, 5].map((i) => parseInt(h.slice(i, i + 2), 16));
  const [fr, fgn, fb] = parse(fg);
  const [br, bgn, bb] = parse(bg);
  const ch = (f: number, b: number) =>
    Math.round(b + (f - b) * amount).toString(16).padStart(2, "0");
  return `#${ch(fr, br)}${ch(fgn, bgn)}${ch(fb, bb)}`;
}

interface Props {
  /** Conta cujos presets estão sendo editados. */
  source: SourceType;
}

export default function BarStyleSettings({ source }: Props) {
  const [bgColor, setBgColor] = useState(DEFAULT_BG);
  const [textColor, setTextColor] = useState(DEFAULT_TEXT);
  const [font, setFont] = useState(DEFAULT_FONT);
  const [name, setName] = useState("");
  const [fonts, setFonts] = useState<{ key: string; label: string }[]>([]);
  const [customized, setCustomized] = useState(false);
  const [dirty, setDirty] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [saved, setSaved] = useState(false);

  useEffect(() => {
    getBarStyle(source)
      .then((s) => {
        setBgColor(s.bg_color);
        setTextColor(s.text_color);
        setFont(s.font);
        setName(s.name);
        setFonts(s.available_fonts);
        setCustomized(s.customized);
      })
      .catch(() => {
        /* backend fora do ar — mantém padrões */
      });
  }, [source]);

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
      const s = await saveBarStyle(source, bgColor, textColor, font, name);
      setBgColor(s.bg_color);
      setTextColor(s.text_color);
      setFont(s.font);
      setName(s.name);
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
      await resetBarStyle(source);
      setBgColor(DEFAULT_BG);
      setTextColor(DEFAULT_TEXT);
      setFont(DEFAULT_FONT);
      setName("");
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
  const stack = fontStack(font);
  // Sem nome salvo, a faixa escreve o canal do vídeo (streamer). O exemplo no
  // preview deixa isso visível em vez de mostrar uma faixa vazia.
  const previewName = (name || "ALANZOKA").toUpperCase();

  return (
    <div className="rounded-2xl bg-gray-900 border border-gray-800 p-6">
      <div>
        <h2 className="text-base font-semibold text-gray-100">Faixa com o nome</h2>
        <p className="text-sm text-gray-500 mt-1">
          No streamer ela divide a facecam da gameplay; no podcast fica colada na
          borda de baixo do banner. Sem nome preenchido ela só aparece no
          streamer, com o nome do canal do vídeo.
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
              {previewName}
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

        <FontField
          value={font}
          onChange={touch<string>(setFont)}
          disabled={busy}
          fonts={fonts}
        />

        <div className="flex items-center gap-2">
          <span className="text-xs text-gray-500">Nome</span>
          <input
            type="text"
            value={name}
            disabled={busy}
            maxLength={MAX_NAME}
            onChange={(e) => touch<string>(setName)(e.target.value)}
            placeholder="@suaconta"
            className="w-40 rounded-lg bg-gray-800 border border-gray-700 px-2 py-1.5 text-sm text-gray-200 outline-none focus:border-gray-500 disabled:opacity-50"
          />
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
