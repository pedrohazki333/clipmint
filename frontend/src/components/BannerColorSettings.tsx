"use client";
import type { SourceType } from "@/lib/types";

import { useEffect, useState } from "react";
import {
  getApiErrorMessage,
  getBannerColors,
  resetBannerColors,
  saveBannerColors,
} from "@/lib/api";
import ColorField, { HEX_RE, toFullHex } from "@/components/ColorField";
import FontField, { DEFAULT_FONT, fontStack } from "@/components/FontField";

const DEFAULT_BG = "#ED2828";
const DEFAULT_TEXT = "#FFFFFF";

interface Props {
  /** Conta cujos presets estão sendo editados. */
  source: SourceType;
}

export default function BannerColorSettings({ source }: Props) {
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
    getBannerColors(source)
      .then((c) => {
        setBgColor(c.bg_color);
        setTextColor(c.text_color);
        setFont(c.font);
        setFonts(c.available_fonts);
        setCustomized(c.customized);
      })
      .catch(() => {
        /* backend fora do ar — mantém padrões */
      });
  }, [source]);

  function update<T>(setter: (v: T) => void) {
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
      const c = await saveBannerColors(source, bgColor, textColor, font);
      setBgColor(c.bg_color);
      setTextColor(c.text_color);
      setFont(c.font);
      setCustomized(true);
      setDirty(false);
      setSaved(true);
    } catch (err) {
      setError(getApiErrorMessage(err, "Não foi possível salvar o estilo do banner."));
    } finally {
      setBusy(false);
    }
  }

  async function handleReset() {
    setBusy(true);
    setError("");
    try {
      await resetBannerColors(source);
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
  const stack = fontStack(font);

  return (
    <div className="rounded-2xl bg-gray-900 border border-gray-800 p-6">
      <div>
        <h2 className="text-base font-semibold text-gray-100">Banner de título</h2>
        <p className="text-sm text-gray-500 mt-1">
          Cores e fonte da faixa de título nos próximos clips gerados.
        </p>
      </div>

      {/* Preview do banner: retângulo de ponta a ponta, como sai no clip */}
      <div
        className="mt-4 rounded overflow-hidden px-5 py-3 text-center select-none"
        style={{ backgroundColor: previewBg }}
      >
        <span
          className="text-sm"
          style={{
            color: previewText,
            fontFamily: stack.family,
            fontWeight: stack.weight,
          }}
        >
          TÍTULO DO CLIP
        </span>
      </div>

      <div className="mt-4 flex flex-wrap items-center gap-6">
        <ColorField
          label="Fundo"
          value={bgColor}
          onChange={update(setBgColor)}
          disabled={busy}
          fallback={DEFAULT_BG}
        />
        <ColorField
          label="Texto"
          value={textColor}
          onChange={update(setTextColor)}
          disabled={busy}
          fallback={DEFAULT_TEXT}
        />
        <FontField
          value={font}
          onChange={update<string>(setFont)}
          disabled={busy}
          fonts={fonts}
        />

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

      {!valid && (
        <p className="mt-3 text-xs text-amber-500/80 bg-amber-900/15 rounded px-3 py-2">
          Use hexadecimal no formato #RRGGBB (ex: #ED2828).
        </p>
      )}
      {error && (
        <p className="mt-3 text-xs text-red-400 bg-red-900/20 rounded px-3 py-2">{error}</p>
      )}
    </div>
  );
}
