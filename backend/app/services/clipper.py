"""
Serviço de corte e composição de clips usando FFmpeg.

Layout final 1080x1920:
  - Capa estática no topo (print de expressão marcante — layout.generate_cover)
  - Banner de título (retângulo vermelho — layout.generate_banner) sobre a emenda
  - Faixa da conta logo abaixo do banner, com o @ repetido (só quando o nicho
    tem um nome configurado — layout.generate_divider_bar, a mesma do streamer)
  - Vídeo rodando embaixo, com legendas. O crop 9:16 é dinâmico (face tracking)
    quando settings.face_tracking_enabled está ligado; caso contrário fica fixo
    no centro do frame.

Filtergraph: [sendcmd →] crop → scale → pad(canvas) → overlay(capa)
             → overlay(banner) → overlay(faixa) → ass → setsar
Tudo em uma única passagem FFmpeg.

O setsar=1 no fim de cada composição não é decorativo: o filtro `scale` do
FFmpeg, quando a proporção do recorte não bate com a do destino, não deforma a
imagem — ele grava a diferença como SAR (pixel não quadrado) no arquivo. O vídeo
sai 1080x1920, mas o player o exibe esticado na horizontal e ele deixa de
preencher a tela 9:16 (barras pretas no TikTok). Fixar SAR 1:1 garante que o que
é gravado é o que é exibido.
"""

import asyncio
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from app.config import settings
from app.services.face_tracker import track_faces, static_tracking, SNAP_THRESHOLD
from app.services.facecam import (
    CamPhase,
    FacecamRect,
    gameplay_crop_x,
    single_phase,
)
from app.services.layout import (
    COVER_H,
    load_bar_style,
    generate_banner,
    generate_banner_collapse_frames,
    generate_title_banner,
    generate_cover,
    generate_divider_bar,
    streamer_geometry,
)
from app.services.subtitler import FONT_SIZE_WORD, generate_ass_subtitles
from app.services.watermark import (
    clip_watermark_path,
    detect_brand_regions,
    user_watermark_path,
)
from app.utils.ffmpeg import run_ffmpeg, get_video_dimensions, probe_video

logger = logging.getLogger(__name__)

CANVAS_W = 1080
CANVAS_H = 1920

# Área do vídeo (parte inferior do canvas); a capa ocupa o topo
VIDEO_W = CANVAS_W
VIDEO_H = CANVAS_H - COVER_H  # 1152

# Centro vertical do banner fica exatamente na emenda capa/vídeo
BANNER_CENTER_Y = COVER_H

# Altura da faixa da conta, colada na borda de baixo do banner. É a mesma
# proporção da faixa do streamer (streamer_bar_frac × altura do canvas), para
# as duas contas terem a mesma espessura de faixa no feed.
COVER_BAR_H = int(CANVAS_H * 0.029) // 2 * 2

# Passo de interpolação dos comandos de crop (s) — 1/30s = atualização por frame
TRACK_CMD_INTERVAL = 1 / 30


async def _encode(
    job_id: str,
    clip_id: str,
    inputs: list[str],
    chain: str,
    duration: float,
    final_path: str,
) -> tuple[str, int]:
    """
    Codifica o clipe final. Um lugar só, para os modos de layout não divergirem
    em qualidade sem ninguém perceber.

    Os parâmetros são os que já estavam no `cut_and_crop` — esta função foi
    extraída sem alterar nenhum deles (ver tests/test_render_filtergraph.py,
    escrito antes da extração justamente para provar isso).
    """
    await run_ffmpeg(
        *inputs,
        "-t", str(duration),
        "-filter_complex", chain,
        "-map", "[outv]",
        "-map", "0:a?",
        "-c:v", "libx264",
        "-preset", "slow",
        "-crf", "18",
        "-maxrate", "12000k",
        "-bufsize", "24000k",
        "-profile:v", "high",
        "-pix_fmt", "yuv420p",
        # Sem estas tags o arquivo não declara em que espaço de cor foi
        # codificado, e cada player/plataforma chuta — é o que faz o mesmo
        # vídeo sair lavado num lugar e saturado em outro. Live do YouTube
        # em SDR é bt709.
        "-colorspace", "bt709",
        "-color_primaries", "bt709",
        "-color_trc", "bt709",
        # Índice do MP4 no começo do arquivo. Não muda a imagem, mas é o que
        # deixa o vídeo tocar antes de baixar inteiro e o que alguns uploaders
        # web esperam para processar sem reler o arquivo todo.
        "-movflags", "+faststart",
        "-c:a", "aac",
        "-b:a", "192k",
        final_path,
        description=f"Render clip {clip_id}",
    )

    file_size = Path(final_path).stat().st_size
    await _log_clip_quality(job_id, clip_id, final_path, file_size)
    return final_path, file_size


async def cut_and_crop(
    job_id: str,
    clip_id: str,
    video_path: str,
    start_time: float,
    end_time: float,
    words: list[dict],
    subtitle_mode: str,
    banner_text: str = "",
    source_type: str | None = None,
    # Perfil que originou o clipe. Decide de qual pasta vêm os presets de
    # marca; None = os do nicho, que é o comportamento de sempre.
    profile_id: str | None = None,
) -> tuple[str, int]:
    """
    Corta o segmento e monta o clip final: capa + banner + vídeo com face
    tracking e legendas.

    Args:
        job_id: ID do job para logging e organização dos arquivos.
        clip_id: ID do clip para nomeação do arquivo de saída.
        video_path: Caminho do vídeo original.
        start_time: Início do clip em segundos.
        end_time: Fim do clip em segundos.
        words: Lista de palavras com timestamps para geração de legendas.
        subtitle_mode: 'word_highlight', 'traditional', ou 'none'.
        banner_text: Título exibido no retângulo vermelho (vazio = sem banner).

    Returns:
        Tupla (output_path, file_size_bytes).
    """
    clip_dir = settings.clips_dir / job_id
    clip_dir.mkdir(parents=True, exist_ok=True)

    duration = end_time - start_time
    logger.info(
        f"[{job_id}] Cutting clip {clip_id}: "
        f"[{start_time:.1f}s–{end_time:.1f}s] ({duration:.1f}s)"
    )

    # Detecta marcas de terceiros primeiro (a capa precisa das regiões);
    # face tracking + capa rodam em paralelo na sequência
    watermark = user_watermark_path(source_type, profile_id)
    brand = await asyncio.to_thread(
        detect_brand_regions, video_path, start_time, end_time
    )
    qr_regions = brand["qr"]
    all_regions = brand["qr"] + brand["static"]

    cover_path = str(clip_dir / f"{clip_id}_cover.png")
    cover_job = asyncio.to_thread(
        generate_cover, video_path, start_time, end_time, cover_path,
        watermark_path=watermark,
        qr_regions=brand["qr"],
        static_regions=brand["static"],
    )
    if settings.face_tracking_enabled:
        tracking, cover_method = await asyncio.gather(
            track_faces(video_path, start_time, end_time), cover_job
        )
    else:
        tracking = static_tracking()
        cover_method = await cover_job
    logger.info(
        f"[{job_id}] Face tracking: method={tracking['method']}, "
        f"keyframes={len(tracking.get('keyframes', []))}, "
        f"confidence={tracking['confidence']:.0%} | cover: {cover_method} | "
        f"QR: {len(qr_regions)} | static marks: {len(brand['static'])} | "
        f"watermark: {'yes' if watermark else 'no'}"
    )

    src_width, src_height = await get_video_dimensions(video_path)
    logger.info(f"[{job_id}] Source: {src_width}x{src_height}")

    crop_w, crop_h = _crop_dimensions(src_width, src_height, VIDEO_W / VIDEO_H)
    cy = _clamp(
        int(src_height * tracking["center_y"] - crop_h / 2), 0, src_height - crop_h
    )

    keyframes = tracking.get("keyframes", [])
    if tracking["method"] == "mediapipe" and len(keyframes) >= 2:
        # Crop dinâmico: sendcmd atualiza o x do crop ao longo do tempo
        cmd_path = str(clip_dir / f"{clip_id}_track.cmd")
        x0 = _write_track_commands(cmd_path, keyframes, duration, src_width, crop_w)
        crop_filter = (
            f"sendcmd=f={_escape_filter_path(cmd_path)},"
            f"crop@dyn={crop_w}:{crop_h}:{x0}:{cy}"
        )
    else:
        x0 = _crop_x(tracking["center_x"], src_width, crop_w)
        crop_filter = f"crop={crop_w}:{crop_h}:{x0}:{cy}"

    # ── Monta o filter_complex ────────────────────────────────────────────────
    inputs = ["-ss", str(start_time), "-i", video_path]
    n_inputs = 1
    parts: list[str] = []

    # Neutralização de marcas de terceiros ANTES do crop (coordenadas da
    # fonte): delogo borra QRs e logos de canal; a logo do usuário é
    # sobreposta nos QRs. Como acontece pré-crop, acompanha o face tracking.
    src_label = "0:v"
    if all_regions:
        delogos = ",".join(
            _delogo_filter(x, y, w, h, src_width, src_height)
            for (x, y, w, h) in all_regions
        )
        parts.append(f"[{src_label}]{delogos}[clean]")
        src_label = "clean"

        if watermark and qr_regions:
            from PIL import Image

            logo_w, logo_h = Image.open(watermark).size
            wm_idx = n_inputs
            inputs += ["-i", watermark]
            n_inputs += 1

            wm_labels = [f"wm{i}" for i in range(len(qr_regions))]
            if len(qr_regions) > 1:
                parts.append(
                    f"[{wm_idx}:v]split={len(qr_regions)}"
                    + "".join(f"[{l}]" for l in wm_labels)
                )
            else:
                parts.append(f"[{wm_idx}:v]null[{wm_labels[0]}]")

            for i, (x, y, w, h) in enumerate(qr_regions):
                scale = min(w * 0.95 / logo_w, h * 0.95 / logo_h)
                lw = max(2, int(logo_w * scale) // 2 * 2)
                lh = max(2, int(logo_h * scale) // 2 * 2)
                ox = x + (w - lw) // 2
                oy = y + (h - lh) // 2
                parts.append(f"[{wm_labels[i]}]scale={lw}:{lh}[ws{i}]")
                parts.append(f"[{src_label}][ws{i}]overlay={ox}:{oy}[qr{i}]")
                src_label = f"qr{i}"

    # vídeo → área inferior do canvas (pad preserva fps/timing do vídeo)
    cover_idx = n_inputs
    inputs += ["-i", cover_path]
    n_inputs += 1
    parts.append(
        f"[{src_label}]{crop_filter},"
        f"scale={VIDEO_W}:{VIDEO_H}:flags=lanczos,"
        f"pad={CANVAS_W}:{CANVAS_H}:0:{COVER_H}:black[base]"
    )
    parts.append(f"[base][{cover_idx}:v]overlay=0:0[withcover]")
    last_label = "withcover"

    bar_bottom = COVER_H  # onde a faixa da conta encosta, se não houver banner

    if banner_text.strip():
        banner_path = str(clip_dir / f"{clip_id}_banner.png")
        _, banner_h = await asyncio.to_thread(
            generate_banner, banner_text, banner_path, None, None, None,
            source_type, profile_id,
        )
        banner_y = BANNER_CENTER_Y - banner_h // 2
        bar_bottom = banner_y + banner_h
        banner_idx = n_inputs
        inputs += ["-i", banner_path]
        n_inputs += 1
        parts.append(
            f"[{last_label}][{banner_idx}:v]"
            f"overlay=(main_w-overlay_w)/2:{banner_y}[withbanner]"
        )
        last_label = "withbanner"

    # Faixa da conta, colada na borda de baixo do banner. Só sai quando o nicho
    # tem um nome configurado: sem isso a faixa escreveria o nome do canal do
    # vídeo de origem — o dono do podcast, não a conta que publica o clipe.
    bar_name = load_bar_style(source_type, profile_id).name
    if bar_name:
        bar_path = str(clip_dir / f"{clip_id}_bar.png")
        await asyncio.to_thread(
            generate_divider_bar,
            CANVAS_W, COVER_BAR_H, bar_path, None,
            bar_name, None, None, None, source_type, profile_id,
        )
        bar_idx = n_inputs
        inputs += ["-i", bar_path]
        n_inputs += 1
        parts.append(f"[{last_label}][{bar_idx}:v]overlay=0:{bar_bottom}[withbar]")
        last_label = "withbar"
        logger.info(
            f"[{job_id}] Faixa da conta {CANVAS_W}x{COVER_BAR_H} em "
            f"y={bar_bottom} ({bar_name!r})"
        )

    if subtitle_mode != "none":
        ass_path = str(clip_dir / f"{clip_id}.ass")
        generate_ass_subtitles(
            words=words,
            start_time=start_time,
            end_time=end_time,
            subtitle_mode=subtitle_mode,
            output_path=ass_path,
        )
        parts.append(
            f"[{last_label}]ass={_escape_filter_path(ass_path)},setsar=1[outv]"
        )
    else:
        parts.append(f"[{last_label}]setsar=1[outv]")

    chain = ";".join(parts)

    final_path = str(clip_dir / f"{clip_id}.mp4")

    # Input seeking (-ss antes de -i) é frame-accurate com re-encode e zera o
    # timestamp do filtergraph — os keyframes do tracking casam 1:1 com o sendcmd.
    return await _encode(
        job_id, clip_id, inputs, chain, duration, final_path
    )


async def _brand_layers(
    video_path: str,
    start_time: float,
    end_time: float,
    source_type: str | None,
    profile_id: str | None,
) -> tuple[list[str], list[str], str, int]:
    """
    Limpeza de marcas de terceiros, aplicada nas coordenadas da FONTE.

    Borra QR e logo de canal com delogo e, havendo QR, cobre cada um com a logo
    do usuário. Devolve (inputs, partes do filtro, rótulo de saída, nº de
    inputs) para quem chama continuar a cadeia.

    Roda antes de qualquer recorte, de propósito: as regiões foram medidas no
    frame original, e cortar antes faria a área borrada não corresponder ao que
    está na tela.
    """
    watermark = user_watermark_path(source_type, profile_id)
    brand = await asyncio.to_thread(
        detect_brand_regions, video_path, start_time, end_time
    )
    qr_regions = brand["qr"]
    all_regions = brand["qr"] + brand["static"]

    inputs = ["-ss", str(start_time), "-i", video_path]
    n_inputs = 1
    parts: list[str] = []
    src_label = "0:v"

    if not all_regions:
        return inputs, parts, src_label, n_inputs

    src_width, src_height = await get_video_dimensions(video_path)
    delogos = ",".join(
        _delogo_filter(x, y, w, h, src_width, src_height)
        for (x, y, w, h) in all_regions
    )
    parts.append(f"[{src_label}]{delogos}[clean]")
    src_label = "clean"

    if watermark and qr_regions:
        from PIL import Image

        logo_w, logo_h = Image.open(watermark).size
        wm_idx = n_inputs
        inputs += ["-i", watermark]
        n_inputs += 1

        wm_labels = [f"wm{i}" for i in range(len(qr_regions))]
        if len(qr_regions) > 1:
            parts.append(
                f"[{wm_idx}:v]split={len(qr_regions)}"
                + "".join(f"[{l}]" for l in wm_labels)
            )
        else:
            parts.append(f"[{wm_idx}:v]null[{wm_labels[0]}]")

        for i, (x, y, w, h) in enumerate(qr_regions):
            scale = min(w * 0.95 / logo_w, h * 0.95 / logo_h)
            lw = max(2, int(logo_w * scale) // 2 * 2)
            lh = max(2, int(logo_h * scale) // 2 * 2)
            ox = x + (w - lw) // 2
            oy = y + (h - lh) // 2
            parts.append(f"[{wm_labels[i]}]scale={lw}:{lh}[ws{i}]")
            parts.append(f"[{src_label}][ws{i}]overlay={ox}:{oy}[qr{i}]")
            src_label = f"qr{i}"

    return inputs, parts, src_label, n_inputs


def _subtitle_tail(
    parts: list[str],
    last_label: str,
    clip_dir: Path,
    clip_id: str,
    words: list[dict],
    start_time: float,
    end_time: float,
    subtitle_mode: str,
) -> None:
    """Fecha a cadeia com a legenda queimada (ou só o setsar, sem ela)."""
    if subtitle_mode != "none":
        ass_path = str(clip_dir / f"{clip_id}.ass")
        generate_ass_subtitles(
            words=words,
            start_time=start_time,
            end_time=end_time,
            subtitle_mode=subtitle_mode,
            output_path=ass_path,
        )
        parts.append(
            f"[{last_label}]ass={_escape_filter_path(ass_path)},setsar=1[outv]"
        )
    else:
        parts.append(f"[{last_label}]setsar=1[outv]")


async def cut_vertical(
    job_id: str,
    clip_id: str,
    video_path: str,
    start_time: float,
    end_time: float,
    words: list[dict],
    subtitle_mode: str,
    source_type: str | None = None,
    profile_id: str | None = None,
    **_ignorados,
) -> tuple[str, int]:
    """
    Crop vertical seco: 9:16 cheio, sem capa, sem banner, sem faixa.

    O enquadramento é CENTRALIZADO, não segue o rosto. É o que "seco" quer
    dizer: o recorte é previsível e igual em todo clipe, e o render não paga o
    MediaPipe. Quem quer o rosto acompanhado usa o modo Capa + Banner.

    A limpeza de marcas de terceiros e a marca d'água continuam valendo — são a
    mesma função dos outros modos.
    """
    clip_dir = settings.clips_dir / job_id
    clip_dir.mkdir(parents=True, exist_ok=True)
    duration = end_time - start_time
    logger.info(
        f"[{job_id}] Crop vertical {clip_id}: "
        f"[{start_time:.1f}s–{end_time:.1f}s] ({duration:.1f}s)"
    )

    inputs, parts, src_label, _ = await _brand_layers(
        video_path, start_time, end_time, source_type, profile_id
    )

    src_width, src_height = await get_video_dimensions(video_path)
    crop_w, crop_h = _crop_dimensions(src_width, src_height, CANVAS_W / CANVAS_H)
    x0 = (src_width - crop_w) // 2
    y0 = (src_height - crop_h) // 2
    logger.info(
        f"[{job_id}] Fonte {src_width}x{src_height} → recorte central "
        f"{crop_w}x{crop_h} em ({x0},{y0})"
    )

    parts.append(
        f"[{src_label}]crop={crop_w}:{crop_h}:{x0}:{y0},"
        f"scale={CANVAS_W}:{CANVAS_H}:flags=lanczos[base]"
    )
    _subtitle_tail(
        parts, "base", clip_dir, clip_id, words, start_time, end_time, subtitle_mode
    )

    final_path = str(clip_dir / f"{clip_id}.mp4")
    return await _encode(job_id, clip_id, inputs, ";".join(parts), duration, final_path)


async def cut_original(
    job_id: str,
    clip_id: str,
    video_path: str,
    start_time: float,
    end_time: float,
    words: list[dict],
    subtitle_mode: str,
    source_type: str | None = None,
    profile_id: str | None = None,
    **_ignorados,
) -> tuple[str, int]:
    """
    Layout original: só o corte, no enquadramento e na resolução da fonte.

    Nada de recorte, nada de canvas vertical — um vídeo 16:9 sai 16:9, um 4K sai
    4K. É o modo para quem vai levar o corte para outro editor, ou publicar onde
    o vertical não é o formato.

    A legenda e a limpeza de marcas continuam valendo: elas não mexem no
    enquadramento, que é o que este modo preserva.
    """
    clip_dir = settings.clips_dir / job_id
    clip_dir.mkdir(parents=True, exist_ok=True)
    duration = end_time - start_time

    src_width, src_height = await get_video_dimensions(video_path)
    logger.info(
        f"[{job_id}] Layout original {clip_id}: "
        f"[{start_time:.1f}s–{end_time:.1f}s] ({duration:.1f}s) "
        f"em {src_width}x{src_height}"
    )

    inputs, parts, src_label, _ = await _brand_layers(
        video_path, start_time, end_time, source_type, profile_id
    )

    # `null` só dá um rótulo à saída: sem nenhum filtro de vídeo, o
    # filter_complex não teria como nomear a cadeia para o -map.
    parts.append(f"[{src_label}]null[base]")
    _subtitle_tail(
        parts, "base", clip_dir, clip_id, words, start_time, end_time, subtitle_mode
    )

    final_path = str(clip_dir / f"{clip_id}.mp4")
    return await _encode(job_id, clip_id, inputs, ";".join(parts), duration, final_path)


async def cut_and_stack(
    job_id: str,
    clip_id: str,
    video_path: str,
    start_time: float,
    end_time: float,
    words: list[dict],
    subtitle_mode: str,
    facecam: FacecamRect | list[CamPhase],
    source_type: str | None = None,
    # Perfil que originou o clipe. Decide de qual pasta vêm os presets de
    # marca; None = os do nicho, que é o comportamento de sempre.
    profile_id: str | None = None,
    banner_text: str = "",
) -> tuple[str, int]:
    """
    Monta o clip no layout de live de streamer: facecam em cima, faixa com a
    a marca do usuário, gameplay embaixo — os dois painéis recortados do MESMO
    vídeo fonte, numa única passagem de FFmpeg.

      ┌──────────────┐
      │   FACECAM    │  crop da caixa da cam, preenchendo o painel
      │ ┌──────────┐ │
      │ │  TÍTULO  │ │  encostado na faixa, sai aos 4s encolhendo dentro dela
      ├── faixa ─────┤  barra escura com o nome configurado, repetido
      │   GAMEPLAY   │  fatia vertical central, desviando da cam
      └──────────────┘

    Resolução vem de settings.streamer_output_width (padrão 1080x1920).

    O streamer muda de cena no meio da live — a cam pula de canto, dá zoom.
    `facecam` aceita a linha do tempo dessas mudanças (uma fase por caixa) e o
    painel de cima troca de recorte na hora certa; uma caixa só significa cam
    parada o clip inteiro.

    Args:
        facecam: caixa da cam em frações da fonte (detectada ou manual), ou a
            lista de fases devolvida por facecam.detect_facecam_phases.
        banner_text: título fixo nos primeiros segundos, encostado acima da
            faixa (vazio = sem banner).

    Returns:
        Tupla (output_path, file_size_bytes).
    """
    clip_dir = settings.clips_dir / job_id
    clip_dir.mkdir(parents=True, exist_ok=True)

    duration = end_time - start_time
    geo = streamer_geometry()

    logger.info(
        f"[{job_id}] Cutting streamer clip {clip_id}: "
        f"[{start_time:.1f}s–{end_time:.1f}s] ({duration:.1f}s) → "
        f"{geo.canvas_w}x{geo.canvas_h}"
    )

    src_width, src_height = await get_video_dimensions(video_path)

    phases = _cam_phases(facecam, duration)
    cam_boxes = [p.rect.to_pixels(src_width, src_height) for p in phases]

    # Gameplay: fatia na proporção do painel de baixo, fechada pelo zoom.
    # A fatia é a mesma o clip inteiro, então tem que escapar das caixas de
    # TODAS as fases — desviar só da caixa atual deixaria a cam aparecer no
    # painel de baixo depois que ela mudasse de lugar.
    zoom = max(1.0, settings.streamer_game_zoom)
    game_w, game_h = _gameplay_crop_size(src_width, src_height, geo.game_aspect, zoom)
    game_x = gameplay_crop_x(src_width, game_w, cam_boxes)
    game_y = (src_height - game_h) // 2 // 2 * 2

    logger.info(
        f"[{job_id}] Source {src_width}x{src_height} | "
        f"gameplay crop {game_w}x{game_h}+{game_x}+{game_y} (zoom {zoom:.2f}x) | "
        f"{len(phases)} fase(s) de facecam"
    )
    for phase, (bx, by, bw, bh) in zip(phases, cam_boxes):
        logger.info(
            f"[{job_id}]   facecam [{phase.start:.1f}s–{phase.end:.1f}s] "
            f"{bw}x{bh}+{bx}+{by} ({phase.rect.method}, {phase.rect.confidence:.0%})"
        )

    # Faixa divisória com o nome repetido. Só o nome configurado entra aqui.
    # Já caiu no canal do vídeo de origem quando ninguém tinha configurado nada,
    # e o clipe saía assinado pelo streamer que gravou — a conta errada.
    bar_path = str(clip_dir / f"{clip_id}_bar.png")
    bar_name = load_bar_style(source_type, profile_id).name
    await asyncio.to_thread(
        generate_divider_bar,
        geo.canvas_w, geo.bar_h, bar_path, user_watermark_path(source_type, profile_id),
        bar_name, None, None, None, source_type, profile_id,
    )

    # Banner de título: PNG estático + os quadros da saída. Só faz sentido se
    # couber no clip — um banner que segura 4s num corte de 3s nunca sairia.
    banner = await _prepare_title_banner(
        clip_dir, clip_id, banner_text, geo, duration, source_type, profile_id
    )
    if banner:
        logger.info(
            f"[{job_id}] Banner de título {geo.canvas_w}x{banner.height} em "
            f"y={banner.y}, some aos {banner.hold:.1f}s em {banner.exit:.2f}s"
        )

    # ── Filter_complex ────────────────────────────────────────────────────────
    # A fonte alimenta o gameplay e um recorte por fase da cam, daí o split.
    #
    # Cada fase é um crop ESTÁTICO próprio, e a troca no tempo é feita pelo
    # `enable` do overlay. Mudar o crop no meio do stream (sendcmd com w/h
    # variáveis) seria o caminho óbvio, mas trava o FFmpeg: o filtro seguinte
    # teria que se reconfigurar a cada mudança de tamanho.
    # Um ramo por CAIXA ÚNICA, não por fase. Num vídeo editado a mesma cam
    # reaparece a cada troca de POV, então 20 fases costumam ser 2 ou 3 caixas
    # se repetindo — e um ramo por fase encheria o filtergraph de recortes
    # idênticos. Agrupando, o custo do render passa a depender de quantos
    # enquadramentos existem, não de quantas vezes a edição alterna entre eles.
    unique_boxes: list[tuple] = []
    box_of_phase: list[int] = []
    for box in cam_boxes:
        if box not in unique_boxes:
            unique_boxes.append(box)
        box_of_phase.append(unique_boxes.index(box))

    cam_labels = [f"cam{i}" for i in range(len(unique_boxes))]
    parts = [
        f"[0:v]split={len(unique_boxes) + 1}[gpsrc]"
        + "".join(f"[fc{i}]" for i in range(len(unique_boxes)))
    ]
    # Só na luminância (croma zerado): realçar o croma levanta o ruído de cor
    # da webcam sem acrescentar nitidez percebida.
    sharpen = (
        f",unsharp=5:5:{settings.facecam_sharpen:.2f}:5:5:0"
        if settings.facecam_sharpen > 0
        else ""
    )
    for i, (cam_x, cam_y, cam_w, cam_h) in enumerate(unique_boxes):
        # A caixa detectada raramente bate com a proporção do painel: amplia
        # até cobrir e recorta o excedente pelo centro (sem barras pretas).
        parts.append(
            f"[fc{i}]crop={cam_w}:{cam_h}:{cam_x}:{cam_y},"
            f"scale={geo.canvas_w}:{geo.facecam_h}:"
            f"force_original_aspect_ratio=increase:flags=lanczos,"
            f"crop={geo.canvas_w}:{geo.facecam_h}{sharpen}[{cam_labels[i]}]"
        )
    parts.append(
        f"[gpsrc]crop={game_w}:{game_h}:{game_x}:{game_y},"
        f"scale={geo.canvas_w}:{geo.game_h}:flags=lanczos,"
        f"pad={geo.canvas_w}:{geo.canvas_h}:0:{geo.game_y}:black[base]"
    )

    # Cada caixa é desenhada nos intervalos em que ela vale, somados num único
    # `enable`. Com a cam voltando para o mesmo canto várias vezes, `gte(t,...)`
    # empilhado não serve — ele só sabe "a partir de", então uma caixa que volta
    # ficaria coberta pela última que começou. `between` marca começo E fim.
    intervals: dict[int, list[tuple[float, float]]] = {}
    for phase, box_index in zip(phases, box_of_phase):
        intervals.setdefault(box_index, []).append((phase.start, phase.end))

    # A caixa que cobre mais tempo é a camada de baixo, desenhada sempre: se
    # algum instante escapar dos intervalos (arredondamento entre fases), ele
    # cai no enquadramento mais provável em vez de ficar sem cam nenhuma.
    base_box = max(
        intervals, key=lambda i: sum(end - start for start, end in intervals[i])
    )
    last_label = "base"
    order = [base_box] + [i for i in intervals if i != base_box]
    for n, box_index in enumerate(order):
        out = f"withcam{n}"
        if box_index == base_box:
            enable = ""
        else:
            spans = "+".join(
                f"between(t,{start:.3f},{end:.3f})"
                for start, end in intervals[box_index]
            )
            enable = f":enable='{spans}'"
        parts.append(
            f"[{last_label}][{cam_labels[box_index]}]overlay=0:0{enable}[{out}]"
        )
        last_label = out

    parts.append(f"[{last_label}][1:v]overlay=0:{geo.facecam_h}[withbar]")
    last_label = "withbar"

    # Os índices dos inputs seguintes dependem de o banner existir ou não, então
    # são contados aqui em vez de escritos à mão. 0 = vídeo fonte, 1 = faixa.
    extra_inputs: list[str] = []
    next_input = 2

    if banner:
        # Duas camadas do mesmo banner, disjuntas no tempo: o PNG parado
        # enquanto ele segura, e a sequência de quadros na saída. Separar assim
        # evita gerar (e decodificar) 4 segundos de quadros idênticos.
        static_idx = next_input
        anim_idx = next_input + 1
        next_input += 2
        extra_inputs += [
            "-i", banner.static_path,
            "-framerate", str(banner.fps), "-i", banner.frames_pattern,
        ]
        parts.append(
            f"[{last_label}][{static_idx}:v]"
            f"overlay=0:{banner.y}:enable='lt(t,{banner.hold:.3f})'[withbanner]"
        )
        # A sequência começa no seu próprio zero; o PTS é empurrado para o
        # instante da saída. Sem isso a animação rodaria no início do clip,
        # por baixo do PNG estático, e o banner simplesmente sumiria aos 4s.
        parts.append(
            f"[{anim_idx}:v]setpts=PTS+{banner.hold:.3f}/TB[bannerout]"
        )
        parts.append(
            f"[withbanner][bannerout]overlay=0:{banner.y}"
            f":enable='between(t,{banner.hold:.3f},{banner.hold + banner.exit:.3f})'"
            f"[withbanneranim]"
        )
        last_label = "withbanneranim"

    # A marca da conta entra depois da faixa e ANTES da legenda: se as duas se
    # encontrarem, quem tem que continuar legível é a legenda.
    watermark_art = clip_watermark_path(source_type, profile_id)
    if watermark_art:
        extra_inputs += ["-i", watermark_art]
        parts.extend(
            _clip_watermark_filters(
                input_idx=next_input,
                base_label=last_label,
                out_label="withwm",
                canvas_w=geo.canvas_w,
                canvas_h=geo.canvas_h,
            )
        )
        next_input += 1
        last_label = "withwm"

    if subtitle_mode != "none":
        ass_path = str(clip_dir / f"{clip_id}.ass")
        generate_ass_subtitles(
            words=words,
            start_time=start_time,
            end_time=end_time,
            subtitle_mode=subtitle_mode,
            output_path=ass_path,
            canvas_w=geo.canvas_w,
            canvas_h=geo.canvas_h,
            margin_v=_streamer_caption_margin(geo),
        )
        parts.append(
            f"[{last_label}]ass={_escape_filter_path(ass_path)},setsar=1[outv]"
        )
    else:
        parts.append(f"[{last_label}]setsar=1[outv]")

    final_path = str(clip_dir / f"{clip_id}.mp4")

    await run_ffmpeg(
        "-ss", str(start_time), "-i", video_path,
        "-i", bar_path,
        *extra_inputs,
        "-t", str(duration),
        "-filter_complex", ";".join(parts),
        "-map", "[outv]",
        "-map", "0:a?",
        "-c:v", "libx264",
        "-preset", "slow",
        "-crf", "18",
        "-maxrate", "12000k",
        "-bufsize", "24000k",
        "-profile:v", "high",
        "-pix_fmt", "yuv420p",
        # Sem estas tags o arquivo não declara em que espaço de cor foi
        # codificado, e cada player/plataforma chuta — é o que faz o mesmo
        # vídeo sair lavado num lugar e saturado em outro. Live do YouTube
        # em SDR é bt709.
        "-colorspace", "bt709",
        "-color_primaries", "bt709",
        "-color_trc", "bt709",
        # Índice do MP4 no começo do arquivo. Não muda a imagem, mas é o que
        # deixa o vídeo tocar antes de baixar inteiro e o que alguns uploaders
        # web esperam para processar sem reler o arquivo todo.
        "-movflags", "+faststart",
        "-c:a", "aac",
        "-b:a", "192k",
        final_path,
        description=f"Render streamer clip {clip_id}",
    )

    file_size = Path(final_path).stat().st_size
    await _log_clip_quality(job_id, clip_id, final_path, file_size)

    return final_path, file_size


@dataclass
class TitleBanner:
    """Os arquivos e a geometria do banner de título já prontos para o overlay."""

    static_path: str
    frames_pattern: str
    fps: int
    height: int
    y: int
    hold: float
    exit: float


async def _prepare_title_banner(
    clip_dir: Path,
    clip_id: str,
    banner_text: str,
    geo,
    duration: float,
    source_type: str | None,
    profile_id: str | None = None,
) -> Optional[TitleBanner]:
    """
    Gera o banner de título e os quadros da saída, ou None se ele não couber.

    None nos três casos em que o banner não faria sentido:

    - sem texto, ou com o tempo de exibição zerado na configuração;
    - num clip curto demais para a animação de saída caber depois do tempo de
      exibição — um banner que nunca sai é um banner que tapa a facecam até o
      fim do clip;
    - se o título não puder ser desenhado. Aqui a falha é engolida de propósito:
      o clip inteiro já foi cortado, e perder o render por causa do adorno seria
      trocar um vídeo bom por nenhum vídeo.
    """
    text = banner_text.strip()
    hold = settings.streamer_banner_hold
    exit_dur = settings.streamer_banner_exit

    if not text or hold <= 0:
        return None
    if duration < hold + exit_dur:
        logger.info(
            f"Clip de {duration:.1f}s é curto demais para o banner "
            f"({hold:.1f}s + {exit_dur:.2f}s de saída) — clip sai sem ele"
        )
        return None

    static_path = str(clip_dir / f"{clip_id}_title.png")
    frames_dir = clip_dir / f"{clip_id}_title_frames"

    try:
        # Argumentos por NOME, e não por posição. Na forma posicional o
        # `profile_id` simplesmente não era passado — e como ele é o último
        # parâmetro, nada acusava: o banner saía com a marca de fábrica do
        # ClipMint enquanto a barra, que passa o perfil, saía com a cor certa.
        # Duas peças do mesmo clipe com marcas diferentes.
        _, height = await asyncio.to_thread(
            generate_title_banner,
            text,
            static_path,
            geo.canvas_w,
            source_type=source_type,
            profile_id=profile_id,
        )
        n_frames = max(2, round(exit_dur * settings.streamer_banner_exit_fps))
        await asyncio.to_thread(
            generate_banner_collapse_frames, static_path, str(frames_dir), n_frames
        )
    except (OSError, ValueError) as exc:
        logger.warning(f"Banner de título não pôde ser gerado ({exc}) — clip sai sem ele")
        return None

    return TitleBanner(
        static_path=static_path,
        frames_pattern=str(frames_dir / "collapse_%03d.png"),
        fps=settings.streamer_banner_exit_fps,
        height=height,
        # Encostado na faixa: a borda de baixo do banner é a de cima da faixa.
        y=geo.facecam_h - height,
        hold=hold,
        exit=exit_dur,
    )


def _cam_phases(
    facecam: FacecamRect | list[CamPhase], duration: float
) -> list[CamPhase]:
    """
    Normaliza o argumento para uma linha do tempo válida.

    Aceita a caixa única (manual ou de um detector antigo) e a lista de fases.
    As fases são ordenadas e presas ao intervalo do clip: uma fase que comece
    depois do fim nunca apareceria, e o `enable` do overlay compara com o
    relógio do filtergraph, que começa em zero.
    """
    if isinstance(facecam, FacecamRect):
        return single_phase(facecam, duration)

    phases = sorted(
        (p for p in facecam if p.start < duration), key=lambda p: p.start
    )
    if not phases:
        raise ValueError("Linha do tempo da facecam vazia")
    phases[0] = CamPhase(0.0, min(phases[0].end, duration), phases[0].rect)
    phases[-1] = CamPhase(phases[-1].start, duration, phases[-1].rect)
    return phases


def _gameplay_crop_size(
    src_w: int, src_h: int, pane_aspect: float, zoom: float
) -> tuple[int, int]:
    """
    Fatia de gameplay recortada da fonte, na proporção EXATA do painel de baixo.

    `pane_aspect` é largura/altura do painel, então a largura sai de
    altura × proporção. Inverter essa conta recorta uma fatia deitada demais: o
    FFmpeg ainda entrega 1080x1920, mas grava o desencontro como SAR anamórfico
    no arquivo — e aí o player estica de volta e o vídeo deixa de preencher a
    tela 9:16 (barras no TikTok).

    A altura sai da fonte fechada pelo zoom; se a largura correspondente não
    couber, a fatia é limitada pela largura e a altura recalculada — nunca
    deformada.
    """
    game_h = max(2, int(src_h / max(1.0, zoom)))
    game_w = int(game_h * pane_aspect)
    if game_w > src_w:
        game_w = src_w
        game_h = min(src_h, int(game_w / pane_aspect))
    return max(2, game_w - game_w % 2), max(2, game_h - game_h % 2)


def _clip_watermark_filters(
    input_idx: int, base_label: str, out_label: str, canvas_w: int, canvas_h: int
) -> list[str]:
    """
    Filtros que escalam a arte, baixam a opacidade e a assentam sobre o clipe.

    A largura vem em fração da largura do canvas e a altura sai por `-1`, então
    a proporção da arte é preservada seja ela qual for. A posição é dada pelo
    CENTRO vertical, e não pelo topo: o topo faria a marca subir ou descer só
    porque a arte é mais alta ou mais baixa, e o que tem que ficar parado entre
    uma arte e outra é o meio dela.

    `colorchannelmixer=aa` multiplica o alfa em vez de substituí-lo — o recorte
    da arte continua recortado, só fica translúcido.
    """
    width = max(2, round(canvas_w * settings.clip_watermark_width))
    opacity = min(1.0, max(0.0, settings.clip_watermark_opacity))
    center_y = round(canvas_h * settings.clip_watermark_center_y)

    return [
        f"[{input_idx}:v]scale={width}:-1:flags=lanczos,"
        f"format=rgba,colorchannelmixer=aa={opacity:.3f}[cwm]",
        # overlay_h só é conhecido pelo FFmpeg em tempo de execução, então o
        # centro vira expressão em vez de número.
        f"[{base_label}][cwm]overlay=(main_w-overlay_w)/2:"
        f"{center_y}-overlay_h/2[{out_label}]",
    ]


def _streamer_caption_margin(geo) -> int:
    """
    MarginV (distância até a borda inferior) que deixa a legenda logo abaixo da
    faixa, no topo do gameplay — como nos clips de live.

    O ASS ancora o texto pela base, então a conta reserva espaço para um bloco
    de duas linhas: assim a legenda desce se quebrar, em vez de invadir a faixa.
    """
    gap = int(0.03 * geo.canvas_h)
    line_h = int(FONT_SIZE_WORD * geo.canvas_w / 1080 * 1.2)
    return max(0, geo.canvas_h - (geo.game_y + gap + 2 * line_h))


def _write_track_commands(
    cmd_path: str,
    keyframes: list[tuple[float, float]],
    duration: float,
    src_width: int,
    crop_w: int,
) -> int:
    """
    Gera o arquivo sendcmd com a posição x do crop interpolada linearmente
    entre os keyframes do face tracker, em passos de TRACK_CMD_INTERVAL.

    Retorna o x inicial (para o valor default do filtro crop).
    """
    lines = []
    last_x = None
    n_steps = int(duration / TRACK_CMD_INTERVAL) + 1
    for i in range(n_steps):
        t = i * TRACK_CMD_INTERVAL
        cx = _interp(keyframes, t)
        x = _crop_x(cx, src_width, crop_w)
        if x != last_x:  # não emite comandos redundantes
            lines.append(f"{t:.3f} crop@dyn x {x};")
            last_x = x

    with open(cmd_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")

    x0 = _crop_x(keyframes[0][1], src_width, crop_w)
    logger.debug(f"Track commands written: {cmd_path} ({len(lines)} updates)")
    return x0


def _interp(keyframes: list[tuple[float, float]], t: float) -> float:
    """
    Interpolação linear de center_x nos keyframes (clampa nas pontas).

    Saltos maiores que SNAP_THRESHOLD são cortes de cena: o crop NÃO desliza
    através deles — segura a posição anterior e pula de uma vez no keyframe.
    """
    if t <= keyframes[0][0]:
        return keyframes[0][1]
    for (t0, x0), (t1, x1) in zip(keyframes, keyframes[1:]):
        if t <= t1:
            if t1 == t0 or abs(x1 - x0) > SNAP_THRESHOLD:
                return x0 if t < t1 else x1
            frac = (t - t0) / (t1 - t0)
            return x0 + frac * (x1 - x0)
    return keyframes[-1][1]


def _delogo_filter(
    x: int, y: int, w: int, h: int, src_w: int, src_h: int
) -> str:
    """Filtro delogo com a região clampada aos limites exigidos pelo FFmpeg
    (a região precisa ficar estritamente dentro do frame)."""
    x = max(1, min(x, src_w - 3))
    y = max(1, min(y, src_h - 3))
    w = max(2, min(w, src_w - x - 1))
    h = max(2, min(h, src_h - y - 1))
    return f"delogo=x={x}:y={y}:w={w}:h={h}"


def _crop_dimensions(
    src_width: int, src_height: int, target_ratio: float
) -> tuple[int, int]:
    """Maior área com a proporção alvo que cabe no vídeo fonte (dimensões pares)."""
    if src_width / src_height > target_ratio:
        crop_h = src_height
        crop_w = int(src_height * target_ratio)
    else:
        crop_w = src_width
        crop_h = int(src_width / target_ratio)
    return crop_w - (crop_w % 2), crop_h - (crop_h % 2)


def _crop_x(center_x: float, src_width: int, crop_w: int) -> int:
    """Posição x do crop para centralizar center_x, clampada nos limites."""
    return _clamp(int(src_width * center_x - crop_w / 2), 0, src_width - crop_w)


def _clamp(v: int, lo: int, hi: int) -> int:
    return max(lo, min(v, hi))


async def _log_clip_quality(
    job_id: str,
    clip_id: str,
    path: str,
    file_size: int,
) -> None:
    size_mb = file_size / 1024 / 1024
    try:
        info = await probe_video(path)
        bitrate_kbps = int(info.get("format", {}).get("bit_rate", 0)) // 1000
        width, height = 0, 0
        for stream in info.get("streams", []):
            if stream.get("codec_type") == "video":
                width = int(stream["width"])
                height = int(stream["height"])
                break
        logger.info(
            f"[{job_id}] Clip {clip_id} quality — "
            f"size={size_mb:.1f}MB, bitrate={bitrate_kbps}kbps, resolution={width}x{height}"
        )
    except Exception as exc:
        logger.warning(f"[{job_id}] Quality probe failed: {exc}")
        logger.info(f"[{job_id}] Clip {clip_id} ready: {size_mb:.1f}MB")


def _escape_filter_path(path: str) -> str:
    """
    Escapa o caminho para uso seguro dentro de um filtro FFmpeg.

    O valor passa por DOIS níveis de parsing (filtergraph e opções do filtro),
    então cada caractere especial precisa de duas barras invertidas para
    sobreviver aos dois. Separadores do Windows são convertidos para '/' — o
    FFmpeg aceita ambos e assim não é preciso escapar barra invertida (que
    exigiria quatro delas e some silenciosamente se faltar alguma).
    """
    return (
        path.replace("\\", "/")
        .replace("'", "\\\\'")
        .replace(":", "\\\\:")
    )
