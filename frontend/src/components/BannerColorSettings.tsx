"use client";

import { useEffect, useState } from "react";
import {
  getApiErrorMessage,
  getBannerColors,
  resetBannerColors,
  saveBannerColors,
} from "@/lib/api";

const DEFAULT_BG = "#ED2828";
const DEFAULT_TEXT = "#FFFFFF";
const HEX_RE = /^#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{6})$/;

/** Expande #RGB para #RRGGBB (input type=color só aceita 6 dígitos). */
function toFullHex(value: string, fallback: string): string {
  if (!HEX_RE.test(value)) return fallback;
  const v = value.slice(1);
  const full = v.length === 3 ? v.split("").map((c) => c + c).join("") : v;
  return `#${full.toUpperCase()}`;
}

function ColorField({
  label,
  value,
  onChange,
  disabled,
  fallback,
}: {
  label: string;
  value: string;
  onChange: (v: string) => void;
  disabled: boolean;
  fallback: string;
}) {
  const valid = HEX_RE.test(value);
  return (
    <div className="flex items-center gap-2">
      <span className="text-xs text-gray-500 w-16">{label}</span>
      <input
        type="color"
        value={toFullHex(value, fallback)}
        disabled={disabled}
        onChange={(e) => onChange(e.target.value.toUpperCase())}
        className="h-8 w-10 rounded cursor-pointer bg-transparent border border-gray-700 disabled:opacity-50"
      />
      <input
        type="text"
        value={value}
        disabled={disabled}
        onChange={(e) => onChange(e.target.value)}
        placeholder="#RRGGBB"
        maxLength={7}
        className={`w-24 rounded-lg bg-gray-800 border px-2 py-1.5 text-sm font-mono text-gray-200 outline-none transition-colors ${
          valid ? "border-gray-700 focus:border-gray-500" : "border-red-700"
        }`}
      />
    </div>
  );
}

export default function BannerColorSettings() {
  const [bgColor, setBgColor] = useState(DEFAULT_BG);
  const [textColor, setTextColor] = useState(DEFAULT_TEXT);
  const [customized, setCustomized] = useState(false);
  const [dirty, setDirty] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [saved, setSaved] = useState(false);

  useEffect(() => {
    getBannerColors()
      .then((c) => {
        setBgColor(c.bg_color);
        setTextColor(c.text_color);
        setCustomized(c.customized);
      })
      .catch(() => {
        /* backend fora do ar — mantém padrões */
      });
  }, []);

  function update(setter: (v: string) => void) {
    return (v: string) => {
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
      const c = await saveBannerColors(bgColor, textColor);
      setBgColor(c.bg_color);
      setTextColor(c.text_color);
      setCustomized(true);
      setDirty(false);
      setSaved(true);
    } catch (err) {
      setError(getApiErrorMessage(err, "Não foi possível salvar as cores."));
    } finally {
      setBusy(false);
    }
  }

  async function handleReset() {
    setBusy(true);
    setError("");
    try {
      await resetBannerColors();
      setBgColor(DEFAULT_BG);
      setTextColor(DEFAULT_TEXT);
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

  return (
    <div className="rounded-2xl bg-gray-900 border border-gray-800 p-6">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <h2 className="text-base font-semibold text-gray-100">Cores do banner</h2>
          <p className="text-sm text-gray-500 mt-1">
            Cor da pílula de título e da fonte nos próximos clips gerados.
          </p>
        </div>

        {/* Preview da pílula */}
        <span
          className="rounded-full px-5 py-2 text-sm font-bold tracking-wide select-none"
          style={{ backgroundColor: previewBg, color: previewText }}
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
          label="Fonte"
          value={textColor}
          onChange={update(setTextColor)}
          disabled={busy}
          fallback={DEFAULT_TEXT}
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
