"use client";

import { useEffect, useState } from "react";

import ClipPreview from "@/components/ClipPreview";
import ColorField from "@/components/ColorField";
import FontField from "@/components/FontField";
import {
  CAPTION_Y_DEFAULT,
  CAPTION_Y_MAX,
  CAPTION_Y_MIN,
  PALETTE,
  WATERMARK_MAX_WIDTH,
  WATERMARK_MIN_OPACITY,
  WATERMARK_MIN_WIDTH,
  captionHeightApplies,
  clampCaptionY,
  defaultStyle,
  watermarkFor,
  withWatermark,
  isHex,
  styleProblems,
  type CaptionEstilo,
  type CaptionTamanho,
  type ClipStyle,
} from "@/lib/clipStyle";
import type { FontOption } from "@/lib/brand";
import { LAYOUT_LABELS } from "@/lib/layouts";
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
  layouts,
  watermarkUrl,
}: {
  value: ClipStyle;
  onChange: (v: ClipStyle) => void;
  /** O layout padrão do perfil: é com ele que a prévia abre. */
  layout: LayoutMode;
  mode: SubtitleMode;
  fonts: FontOption[];
  disabled?: boolean;
  /** Os layouts deste nicho, para ver a prévia (e posicionar a marca) em cada um. */
  layouts: LayoutMode[];
  /** A arte da marca d'água do clipe; null = nenhuma enviada. */
  watermarkUrl: string | null;
}) {
  // A prévia pode mostrar outro layout sem mudar o padrão do perfil: a marca d'água
  // tem uma posição por layout, e é aqui que se escolhe qual está sendo ajustada.
  const [layoutPrevia, setLayoutPrevia] = useState<LayoutMode>(layout);
  useEffect(() => setLayoutPrevia(layout), [layout]);
  const previa = layouts.includes(layoutPrevia) ? layoutPrevia : layout;
  const nomeDaPrevia = LAYOUT_LABELS[previa].nome;

  const marca = watermarkFor(value, previa);
  const mudarMarca = (mudanca: Parameters<typeof withWatermark>[2]) =>
    onChange(withWatermark(value, previa, mudanca));
  const ligadaEm = layouts.filter((l) => watermarkFor(value, l).ligado);

  const problemas = styleProblems(value);
  const alturaVale = captionHeightApplies(previa);
  const altura = value.legenda.altura ?? CAPTION_Y_DEFAULT;
  const moverLegenda = (nova: number) =>
    onChange({ ...value, legenda: { ...value.legenda, altura: clampCaptionY(nova) } });
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
          {layouts.length > 1 && (
            <div className="mb-2 flex flex-wrap gap-1.5" role="group" aria-label="Layout da prévia">
              {layouts.map((l) => (
                <button
                  key={l}
                  type="button"
                  aria-pressed={previa === l}
                  onClick={() => setLayoutPrevia(l)}
                  className={`rounded-sm border px-2.5 py-1 text-label transition-colors ${
                    previa === l
                      ? "border-mint bg-mint-soft text-ink"
                      : "border-line bg-inset text-ink-dim hover:border-line-strong"
                  }`}
                >
                  {LAYOUT_LABELS[l].nome}
                </button>
              ))}
            </div>
          )}
          <ClipPreview
            style={value}
            layout={previa}
            mode={mode}
            onMoverLegenda={disabled ? undefined : moverLegenda}
            watermarkUrl={watermarkUrl}
            onMoverMarca={disabled ? undefined : (x, y) => mudarMarca({ x, y })}
          />
          <p className="mt-2 text-label text-ink-muted">
            Prévia com texto de exemplo.
            {alturaVale && mode !== "none" && !disabled && " Arraste a legenda para mudar a altura."}
            {watermarkUrl && marca.ligado && !disabled && " Arraste a marca d'água para posicioná-la."}
          </p>
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
              Aparece na palavra em destaque do título e no @ da faixa.
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
            <div className="flex flex-col gap-1.5">
              <div className="flex items-center justify-between gap-3">
                <label htmlFor="cm-legenda-altura" className="text-body text-ink-dim">
                  Altura na tela
                </label>
                {altura !== CAPTION_Y_DEFAULT && (
                  <button
                    type="button"
                    disabled={disabled}
                    onClick={() => moverLegenda(CAPTION_Y_DEFAULT)}
                    className="text-label text-ink-muted underline-offset-2 hover:text-ink hover:underline disabled:opacity-50"
                  >
                    Voltar ao padrão
                  </button>
                )}
              </div>
              {/* Invertido: à direita a legenda desce, como ela anda na prévia. */}
              <div className="flex items-center gap-3">
                <span className="text-label text-ink-muted">Mais alto</span>
                <input
                  id="cm-legenda-altura"
                  type="range"
                  min={CAPTION_Y_MIN}
                  max={CAPTION_Y_MAX}
                  step={5}
                  value={altura}
                  disabled={disabled || !alturaVale}
                  onChange={(e) => moverLegenda(Number(e.target.value))}
                  aria-valuetext={`${Math.round(((altura - CAPTION_Y_MIN) / (CAPTION_Y_MAX - CAPTION_Y_MIN)) * 100)}% para baixo`}
                  className="w-full max-w-xs accent-[var(--color-ink)]"
                />
                <span className="text-label text-ink-muted">Mais baixo</span>
              </div>
              <p className="text-label text-ink-muted">
                {alturaVale
                  ? "Desça a legenda se ela cobre o rosto de quem fala. Os limites a mantêm longe da interface do TikTok."
                  : "Neste layout a legenda tem lugar fixo; a altura vale para tela cheia, capa + banner e crop."}
              </p>
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
                className="w-full max-w-xs rounded-sm border border-line bg-inset px-3 py-2 text-body text-ink placeholder-ink-muted outline-none focus:border-ink"
              />
            )}
          </Grupo>

          <Grupo titulo="Marca d'água do clipe">
            {!watermarkUrl ? (
              <p className="text-label text-ink-muted">
                Envie a arte em &ldquo;Marca d&apos;água do clipe&rdquo;, na seção Marca mais
                abaixo, e salve. Depois é só escolher aqui em quais layouts ela aparece e
                arrastá-la na prévia.
              </p>
            ) : (
              <>
                <label className="flex items-center gap-2 text-body text-ink-dim">
                  <input
                    type="checkbox"
                    checked={marca.ligado}
                    disabled={disabled}
                    onChange={(e) => mudarMarca({ ligado: e.target.checked })}
                  />
                  Mostrar no layout {nomeDaPrevia}
                </label>
                {marca.ligado && (
                  <>
                    <div className="flex items-center gap-3">
                      <label htmlFor="cm-marca-tamanho" className="w-20 text-label text-ink-muted">
                        Tamanho
                      </label>
                      <input
                        id="cm-marca-tamanho"
                        type="range"
                        min={Math.round(WATERMARK_MIN_WIDTH * 100)}
                        max={Math.round(WATERMARK_MAX_WIDTH * 100)}
                        step={1}
                        value={Math.round(marca.largura * 100)}
                        disabled={disabled}
                        onChange={(e) => mudarMarca({ largura: Number(e.target.value) / 100 })}
                        aria-valuetext={`${Math.round(marca.largura * 100)}% da largura do vídeo`}
                        className="w-full max-w-xs accent-[var(--color-ink)]"
                      />
                      <span className="w-10 text-right text-label text-ink-muted">
                        {Math.round(marca.largura * 100)}%
                      </span>
                    </div>
                    <div className="flex items-center gap-3">
                      <label htmlFor="cm-marca-opacidade" className="w-20 text-label text-ink-muted">
                        Opacidade
                      </label>
                      <input
                        id="cm-marca-opacidade"
                        type="range"
                        min={Math.round(WATERMARK_MIN_OPACITY * 100)}
                        max={100}
                        step={5}
                        value={Math.round(marca.opacidade * 100)}
                        disabled={disabled}
                        onChange={(e) => mudarMarca({ opacidade: Number(e.target.value) / 100 })}
                        aria-valuetext={`${Math.round(marca.opacidade * 100)}%`}
                        className="w-full max-w-xs accent-[var(--color-ink)]"
                      />
                      <span className="w-10 text-right text-label text-ink-muted">
                        {Math.round(marca.opacidade * 100)}%
                      </span>
                    </div>
                  </>
                )}
                <p className="text-label text-ink-muted">
                  Cada layout guarda a sua posição: troque o layout acima da prévia para
                  ajustar outro.{" "}
                  {ligadaEm.length
                    ? `Aparece em: ${ligadaEm.map((l) => LAYOUT_LABELS[l].nome).join(", ")}.`
                    : "Não aparece em nenhum layout."}
                </p>
              </>
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
