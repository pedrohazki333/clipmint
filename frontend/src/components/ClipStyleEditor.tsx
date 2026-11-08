"use client";

import ClipPreview from "@/components/ClipPreview";
import ColorField from "@/components/ColorField";
import FontField from "@/components/FontField";
import {
  PALETTE,
  defaultStyle,
  isHex,
  styleProblems,
  type CaptionEstilo,
  type CaptionTamanho,
  type ClipStyle,
} from "@/lib/clipStyle";
import type { FontOption } from "@/lib/brand";
import type { LayoutMode, SubtitleMode } from "@/lib/types";

/**
 * O visual dos clipes do perfil, com a prévia ao lado.
 *
 * Campo controlado, como os painéis de marca: quem grava é o "Salvar" do formulário.
 * Uma cor que não se lê é avisada na hora, e o botão de salvar fica travado; o servidor
 * aplica a mesma regra.
 */

const ESTILOS: { valor: CaptionEstilo; nome: string; descricao: string }[] = [
  { valor: "caixa", nome: "Caixa", descricao: "A palavra falada ganha uma caixa colorida" },
  { valor: "cor", nome: "Cor", descricao: "A palavra falada muda de cor" },
];

const TAMANHOS: { valor: CaptionTamanho; nome: string }[] = [
  { valor: "P", nome: "Pequena" },
  { valor: "M", nome: "Média" },
  { valor: "G", nome: "Grande" },
];

function Paleta({
  value,
  onChange,
  disabled,
  rotulo,
}: {
  value: string;
  onChange: (v: string) => void;
  disabled?: boolean;
  rotulo: string;
}) {
  return (
    <div className="flex flex-wrap items-center gap-3">
      <div className="flex gap-2" role="group" aria-label={`Paleta: ${rotulo}`}>
        {Object.entries(PALETTE).map(([nome, cor]) => (
          <button
            key={nome}
            type="button"
            title={nome}
            aria-label={nome}
            aria-pressed={value.toUpperCase() === cor}
            disabled={disabled}
            onClick={() => onChange(cor)}
            style={{ background: cor }}
            className={`h-8 w-8 rounded-sm border-2 transition-transform disabled:opacity-50 ${
              value.toUpperCase() === cor ? "border-ink" : "border-transparent hover:scale-105"
            }`}
          />
        ))}
      </div>
      <ColorField
        label="Livre"
        value={value}
        onChange={onChange}
        disabled={Boolean(disabled)}
        fallback={isHex(value) ? value : PALETTE.rosa}
      />
    </div>
  );
}

function Grupo({ titulo, children }: { titulo: string; children: React.ReactNode }) {
  return (
    <fieldset className="flex flex-col gap-2">
      <legend className="mb-1 text-body text-ink">{titulo}</legend>
      {children}
    </fieldset>
  );
}

export default function ClipStyleEditor({
  value,
  onChange,
  layout,
  mode,
  fonts,
  disabled,
}: {
  value: ClipStyle;
  onChange: (v: ClipStyle) => void;
  layout: LayoutMode;
  mode: SubtitleMode;
  fonts: FontOption[];
  disabled?: boolean;
}) {
  const problemas = styleProblems(value);
  const opcoesDeFonte = [
    { key: "archivo", label: "Archivo" },
    ...fonts.filter((f) => f.key !== "archivo"),
  ];

  return (
    <div className="border-t border-line pt-6" data-testid="clip-style-editor">
      <p className="mb-1 text-body font-medium text-ink">Estilo do clipe</p>
      <p className="mb-4 text-label text-ink-muted">
        Como o título e a legenda aparecem nos clipes deste perfil. Vale para os próximos
        vídeos, e não muda os que já foram gerados.
      </p>

      <div className="flex flex-col gap-6 lg:flex-row-reverse lg:items-start lg:justify-end">
        <div className="w-full lg:sticky lg:top-4 lg:w-[405px] lg:flex-shrink-0">
          <ClipPreview style={value} layout={layout} mode={mode} />
          <p className="mt-2 text-label text-ink-muted">Prévia com texto de exemplo.</p>
        </div>

        <div className="flex min-w-0 flex-1 flex-col gap-5">
          <Grupo titulo="Cor da marca">
            <Paleta
              rotulo="cor da marca"
              value={value.marca}
              onChange={(marca) => onChange({ ...value, marca })}
              disabled={disabled}
            />
            <p className="text-label text-ink-muted">
              Aparece na palavra em destaque do título e nas bordas da faixa.
            </p>
          </Grupo>

          <Grupo titulo="Legenda">
            <div className="flex flex-col gap-2 sm:flex-row">
              {ESTILOS.map((estilo) => (
                <button
                  key={estilo.valor}
                  type="button"
                  disabled={disabled}
                  aria-pressed={value.legenda.estilo === estilo.valor}
                  onClick={() =>
                    onChange({ ...value, legenda: { ...value.legenda, estilo: estilo.valor } })
                  }
                  className={`flex-1 rounded-sm border px-3 py-2 text-left transition-colors disabled:opacity-50 ${
                    value.legenda.estilo === estilo.valor
                      ? "border-mint bg-mint-soft text-ink"
                      : "border-line bg-inset text-ink-dim hover:border-line-strong"
                  }`}
                >
                  <span className="block text-body font-medium">{estilo.nome}</span>
                  <span className="block text-label">{estilo.descricao}</span>
                </button>
              ))}
            </div>
            <Paleta
              rotulo="cor da legenda"
              value={value.legenda.cor}
              onChange={(cor) => onChange({ ...value, legenda: { ...value.legenda, cor } })}
              disabled={disabled}
            />
            <div className="flex gap-2" role="group" aria-label="Tamanho da legenda">
              {TAMANHOS.map((tamanho) => (
                <button
                  key={tamanho.valor}
                  type="button"
                  disabled={disabled}
                  aria-pressed={value.legenda.tamanho === tamanho.valor}
                  onClick={() =>
                    onChange({ ...value, legenda: { ...value.legenda, tamanho: tamanho.valor } })
                  }
                  className={`rounded-sm border px-3 py-1.5 text-body transition-colors disabled:opacity-50 ${
                    value.legenda.tamanho === tamanho.valor
                      ? "border-mint bg-mint-soft text-ink"
                      : "border-line bg-inset text-ink-dim hover:border-line-strong"
                  }`}
                >
                  {tamanho.nome}
                </button>
              ))}
            </div>
          </Grupo>

          <Grupo titulo="Título">
            <label className="flex items-center gap-2 text-body text-ink-dim">
              <input
                type="checkbox"
                checked={value.titulo.ligado}
                disabled={disabled}
                onChange={(e) =>
                  onChange({ ...value, titulo: { ...value.titulo, ligado: e.target.checked } })
                }
              />
              Mostrar o título no clipe
            </label>
            {value.titulo.ligado && (
              <div className="flex flex-wrap gap-4">
                <ColorField
                  label="Fundo"
                  value={value.titulo.fundo}
                  onChange={(fundo) =>
                    onChange({ ...value, titulo: { ...value.titulo, fundo } })
                  }
                  disabled={Boolean(disabled)}
                  fallback={defaultStyle().titulo.fundo}
                />
                <ColorField
                  label="Texto"
                  value={value.titulo.texto}
                  onChange={(texto) =>
                    onChange({ ...value, titulo: { ...value.titulo, texto } })
                  }
                  disabled={Boolean(disabled)}
                  fallback={defaultStyle().titulo.texto}
                />
              </div>
            )}
          </Grupo>

          <Grupo titulo="Nome da conta">
            <label className="flex items-center gap-2 text-body text-ink-dim">
              <input
                type="checkbox"
                checked={value.arroba.ligado}
                disabled={disabled}
                onChange={(e) =>
                  onChange({ ...value, arroba: { ...value.arroba, ligado: e.target.checked } })
                }
              />
              Mostrar o @ no clipe
            </label>
            {value.arroba.ligado && (
              <input
                aria-label="Nome da conta"
                value={value.arroba.texto}
                disabled={disabled}
                maxLength={40}
                placeholder="@suaconta"
                onChange={(e) =>
                  onChange({ ...value, arroba: { ...value.arroba, texto: e.target.value } })
                }
                className="w-full max-w-xs rounded-sm border border-line bg-inset px-3 py-2 text-body text-ink placeholder-ink-muted outline-none focus:border-mint"
              />
            )}
          </Grupo>

          <Grupo titulo="Fonte">
            <FontField
              value={value.fonte}
              onChange={(fonte) => onChange({ ...value, fonte })}
              disabled={Boolean(disabled)}
              fonts={opcoesDeFonte}
              label="Fonte"
            />
          </Grupo>

          {problemas.length > 0 && (
            <ul
              role="alert"
              className="rounded-sm border border-danger/40 bg-danger-soft px-3 py-2 text-body text-danger"
            >
              {problemas.map((problema) => (
                <li key={problema}>{problema}</li>
              ))}
            </ul>
          )}
        </div>
      </div>
    </div>
  );
}
