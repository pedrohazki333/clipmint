"""
Testes da camada de visão.

Nenhum teste aqui chama a API nem o ffmpeg: o que se verifica é a lógica que
decide o que fazer com a resposta — que é onde os erros custam corte errado.

O caso de referência é o mesmo do resto do projeto: o clipe do Fall, em que a
tela do streamer não mostra o acontecimento (ele estava pescando do outro lado
da ilha) e o sinal visual está na facecam, no riso.
"""

import asyncio

import pytest

from app.services.analyzer import _bounds_question, _refine_bounds_with_vision, _snap_to_word
from app.services.audio_events import Gap
from app.prompts.viral_analysis import format_gap
from app.services.vision import Keyframe, Scene


WORDS = [
    {"text": "Você", "start": 3023.9, "end": 3024.2},
    {"text": "joga", "start": 3024.3, "end": 3024.7},
    {"text": "cara?", "start": 3030.1, "end": 3030.4},
    {"text": "Finalmente", "start": 3051.8, "end": 3052.4},
]


def _clip(start, end, **kw):
    base = {"start": start, "end": end, "_segments": [], "trim_reason": "", "verdict": "post"}
    base.update(kw)
    return base


def _run(clips, scene, max_duration=90, monkeypatch=None):
    """Roda o refino com uma resposta de visão fixa."""
    async def fake_look_many(job_id, video_path, windows, questions):
        return [scene] * len(windows)

    from app.services import analyzer
    monkeypatch.setattr(analyzer.vision, "look_many", fake_look_many)
    asyncio.run(
        _refine_bounds_with_vision("job", "/v.mp4", clips, WORDS, max_duration)
    )


# ─── A regra central: só afrouxa ──────────────────────────────────────────────

def test_visao_estica_o_inicio_para_tras(monkeypatch):
    """O acontecimento começa antes do corte: o corte volta para pegá-lo."""
    clips = [_clip(3040.0, 3083.3)]
    _run(clips, Scene(on_screen="cena", event_start=3026.8, event_end=None), monkeypatch=monkeypatch)

    assert clips[0]["start"] == 3026.8
    assert clips[0]["end"] == 3083.3


def test_visao_estica_o_fim_para_frente(monkeypatch):
    clips = [_clip(3028.1, 3050.0)]
    _run(clips, Scene(on_screen="cena", event_start=None, event_end=3062.8), monkeypatch=monkeypatch)

    assert clips[0]["start"] == 3028.1
    assert clips[0]["end"] == 3062.8


def test_visao_nunca_aperta_o_corte(monkeypatch):
    """
    O acontecimento cabe folgado dentro do corte — e mesmo assim nada encolhe.

    Perder o fato custa o clipe inteiro; sobrar alguns segundos não custa nada.
    """
    clips = [_clip(3028.1, 3083.3)]
    _run(clips, Scene(on_screen="cena", event_start=3040.0, event_end=3060.0), monkeypatch=monkeypatch)

    assert clips[0]["start"] == 3028.1
    assert clips[0]["end"] == 3083.3


def test_respeita_o_teto_de_duracao(monkeypatch):
    """Não cabendo tudo, sacrifica o começo — o fim é onde está a reação."""
    clips = [_clip(3060.0, 3083.3)]
    _run(clips, Scene(on_screen="cena", event_start=3000.0, event_end=None),
         max_duration=40, monkeypatch=monkeypatch)

    assert clips[0]["end"] == 3083.3
    assert clips[0]["end"] - clips[0]["start"] == pytest.approx(40.0)


def test_nao_toca_em_clipe_costurado(monkeypatch):
    clips = [_clip(3040.0, 3083.3, _segments=[(3040.0, 3050.0), (3060.0, 3083.3)])]
    _run(clips, Scene(on_screen="cena", event_start=3000.0), monkeypatch=monkeypatch)

    assert clips[0]["start"] == 3040.0


def test_sem_resposta_da_visao_nada_muda(monkeypatch):
    clips = [_clip(3028.1, 3083.3)]
    _run(clips, None, monkeypatch=monkeypatch)

    assert clips[0]["start"] == 3028.1
    assert clips[0]["trim_reason"] == ""


# ─── A visão não vota no veredito ─────────────────────────────────────────────

def test_visao_nunca_muda_o_veredito(monkeypatch):
    """
    Uma versão anterior marcava `revisar_corte` a partir de um booleano da
    visão. O campo devolveu respostas opostas para a MESMA janela em duas
    execuções seguidas, então saiu — e não pode voltar sem querer.
    """
    clips = [_clip(3028.1, 3083.3)]
    _run(clips, Scene(on_screen="nada de especial acontece", reaction=None),
         monkeypatch=monkeypatch)

    assert clips[0]["verdict"] == "post"


def test_scene_nao_tem_campo_de_julgamento():
    assert not hasattr(Scene(on_screen="x"), "anything_happens")


def test_descricao_fica_registrada_mesmo_sem_mudar_o_corte(monkeypatch):
    """Um mês depois dá para saber o que havia ali sem reabrir o vídeo."""
    clips = [_clip(3028.1, 3083.3)]
    _run(clips, Scene(on_screen="o jogador pesca", reaction="gargalhada aberta"),
         monkeypatch=monkeypatch)

    assert "o jogador pesca" in clips[0]["trim_reason"]
    assert "gargalhada aberta" in clips[0]["trim_reason"]


# ─── Corte no meio da palavra ─────────────────────────────────────────────────

def test_snap_recua_ate_o_comeco_da_palavra():
    """O keyframe cai onde o codificador quis, não onde a frase começa."""
    assert _snap_to_word(WORDS, 3024.5) == 3024.3


def test_snap_ignora_instante_no_silencio():
    assert _snap_to_word(WORDS, 3040.0) == 3040.0


# ─── Montagem da pergunta ─────────────────────────────────────────────────────

def test_pergunta_nao_quebra_com_as_chaves_do_json():
    """
    O exemplo de JSON tem chaves; usar `.format()` nele levantava KeyError.
    """
    q = _bounds_question(3028.1, 3083.3)
    assert "3028.1" in q and "3083.3" in q
    assert '"on_screen"' in q


# ─── A anotação que chega ao modelo ───────────────────────────────────────────

def test_anotacao_carrega_a_descricao_quando_existe():
    gap = Gap(start=3030.4, end=3051.8, loudness=-14.1, speech_level=-27.6)
    gap.scene = "o personagem é arremessado. Reação: gargalhada"

    line = format_gap(gap)
    assert "NA IMAGEM" in line
    assert "arremessado" in line


def test_anotacao_sem_descricao_continua_como_antes():
    """Visão desligada ou falha: a anotação volta a ser só a medição."""
    gap = Gap(start=3030.4, end=3051.8, loudness=-14.1, speech_level=-27.6)

    line = format_gap(gap)
    assert "ÁUDIO ALTO" in line
    assert "NA IMAGEM" not in line


# ─── Amostragem de quadros ────────────────────────────────────────────────────

def test_scene_summary_junta_cena_e_reacao():
    s = Scene(on_screen="o jogador pesca", reaction="rindo alto")
    assert s.summary() == "o jogador pesca Reação: rindo alto"


def test_scene_summary_sem_facecam():
    assert Scene(on_screen="o jogador pesca").summary() == "o jogador pesca"


def test_keyframe_guarda_o_instante():
    f = Keyframe(time=3032.8, jpeg=b"\xff\xd8")
    assert f.time == 3032.8


# ─── Quais janelas a visão olha ───────────────────────────────────────────────

def _strong(start, above_speech):
    """Evento forte o bastante para a visão (>= +6 dB e >= 4s)."""
    return Gap(start=start, end=start + 6.0, loudness=-24.3 + above_speech,
               speech_level=-24.3)


def test_visao_escolhe_os_eventos_mais_fortes_do_video_inteiro(monkeypatch):
    """
    A seleção é por INTENSIDADE, não por ordem.

    Com fatia cronológica, um vídeo de horas era olhado só no começo: medido no
    do alanzoka (110 min, 74 eventos fortes), as 20 janelas paravam em 52:30 e
    a metade de trás não era vista por ninguém.
    """
    from app.services import scene_events

    gaps = [_strong(t, db) for t, db in
            ((30.0, 6.5), (60.0, 7.0), (90.0, 6.2), (6000.0, 18.0), (6400.0, 15.0))]

    seen = []

    async def fake_look_many(job_id, video_path, windows, questions):
        seen.extend(windows)
        return [None] * len(windows)

    monkeypatch.setattr(scene_events.vision, "look_many", fake_look_many)
    monkeypatch.setattr(scene_events.settings, "vision_max_windows", 2)

    asyncio.run(scene_events.describe_events("job", "/v.mp4", gaps))

    starts = sorted(round(w[0] + scene_events._MARGIN) for w in seen)
    assert starts == [6000, 6400]


def test_visao_entrega_as_janelas_em_ordem_cronologica(monkeypatch):
    """Escolher por intensidade não pode embaralhar a linha do tempo."""
    from app.services import scene_events

    gaps = [_strong(t, db) for t, db in ((100.0, 9.0), (50.0, 20.0), (200.0, 12.0))]
    seen = []

    async def fake_look_many(job_id, video_path, windows, questions):
        seen.extend(windows)
        return [None] * len(windows)

    monkeypatch.setattr(scene_events.vision, "look_many", fake_look_many)
    monkeypatch.setattr(scene_events.settings, "vision_max_windows", 3)

    asyncio.run(scene_events.describe_events("job", "/v.mp4", gaps))

    assert seen == sorted(seen)


def test_pergunta_procura_o_que_muda_e_nao_o_cenario():
    """
    A pergunta é o que decide se o gag visual é achado.

    Medido na janela [3840-3850] do vídeo do alanzoka, com os mesmos quadros:
    "descreva o que se vê" devolveu "sem evento marcante visível", enquanto
    perguntar o que MUDA achou o personagem de outro jogador atravessando a
    tela — que era o clipe inteiro.
    """
    from app.services.scene_events import _QUESTION

    assert "MUDA" in _QUESTION
    assert "outros jogadores" in _QUESTION
    assert "Descreva o que se vê" not in _QUESTION
