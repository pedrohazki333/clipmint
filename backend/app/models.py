from datetime import datetime, timezone
from uuid import uuid4
from sqlalchemy import Column, String, Float, Integer, Text, DateTime, ForeignKey
from sqlalchemy.orm import relationship

from app.database import Base


def uuid4_hex() -> str:
    return uuid4().hex


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Job(Base):
    __tablename__ = "jobs"

    id = Column(String, primary_key=True, default=uuid4_hex)
    youtube_url = Column(String, nullable=False)
    video_title = Column(String, nullable=True)
    channel_name = Column(String, nullable=True)
    duration_seconds = Column(Float, nullable=True)
    thumbnail_url = Column(String, nullable=True)
    video_path = Column(String, nullable=True)
    audio_path = Column(String, nullable=True)
    subtitle_mode = Column(String, default="word_highlight")  # word_highlight | traditional | none
    layout_mode = Column(String, default="cover")   # cover (capa+banner) | streamer (facecam+gameplay)
    # Muda a rubrica da análise (critérios de podcast x gameplay) e define em
    # qual conta o clip é postado no cronograma. Default vem do layout_mode.
    source_type = Column(String, default="podcast")  # podcast | gameplay
    # Caixa da facecam em frações da fonte, JSON {x,y,w,h,confidence,method}.
    # Detectada no 1º clip e reusada nos demais; editável pelo usuário.
    facecam_rect = Column(Text, nullable=True)
    status = Column(String, default="queued")  # queued|downloading|transcribing|analyzing|clipping|done|error
    error_message = Column(String, nullable=True)
    created_at = Column(DateTime(timezone=True), default=utcnow)
    updated_at = Column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    transcript = relationship("Transcript", back_populates="job", uselist=False)
    clips = relationship("Clip", back_populates="job")


class Transcript(Base):
    __tablename__ = "transcripts"

    id = Column(String, primary_key=True, default=uuid4_hex)
    job_id = Column(String, ForeignKey("jobs.id"), nullable=False)
    full_text = Column(Text, nullable=False)
    words_json_path = Column(String, nullable=False)  # path pro JSON com word-level timestamps
    language = Column(String, nullable=True)
    confidence = Column(Float, nullable=True)
    created_at = Column(DateTime(timezone=True), default=utcnow)

    job = relationship("Job", back_populates="transcript")


class ReferenceExample(Base):
    """
    Exemplo de aprendizado a partir de um clipe viral de OUTRO criador.

    O usuário fornece a URL do vídeo original + o arquivo do clipe viral.
    O pipeline localiza onde o clipe foi cortado dentro do original (alinhamento
    de transcrições), pede ao Claude uma análise reversa de por que aquele trecho
    viralizou e, após confirmação do usuário, publica o resultado como exemplo
    validado few-shot em prompt_engine/examples/validated/.

    Pipeline de status:
      queued → downloading_source → transcribing → aligning → analyzing → done
      (qualquer etapa pode ir para: error)
    """

    __tablename__ = "reference_examples"

    id = Column(String, primary_key=True, default=uuid4_hex)
    source_url = Column(String, nullable=False)      # URL do vídeo original (YouTube)
    clip_path = Column(String, nullable=False)       # arquivo do clipe viral enviado

    # Metadados do vídeo original (preenchidos após download)
    source_title = Column(String, nullable=True)
    source_channel = Column(String, nullable=True)
    source_duration = Column(Float, nullable=True)
    language = Column(String, nullable=True)

    # Resultado do alinhamento clipe ↔ original
    source_start = Column(Float, nullable=True)
    source_end = Column(Float, nullable=True)
    alignment_confidence = Column(Float, nullable=True)  # 0.0–1.0
    clip_duration = Column(Float, nullable=True)

    # Análise reversa gerada pelo Claude (JSON serializado)
    analysis_json = Column(Text, nullable=True)      # {hook, suggested_title, reason, tags, virality_score}
    opening_phrase = Column(String, nullable=True)
    transcript_excerpt = Column(Text, nullable=True)

    # Dados fornecidos pelo usuário na confirmação (performance real)
    performance = Column(String, nullable=True)      # viral | muito_bom | bom
    views = Column(Integer, nullable=True)
    notas = Column(Text, nullable=True)

    # Estado
    status = Column(String, default="queued")        # ver docstring
    error_message = Column(String, nullable=True)
    published = Column(Integer, default=0)           # 1 = já gravado em validated/
    example_path = Column(String, nullable=True)     # caminho do JSON publicado
    created_at = Column(DateTime(timezone=True), default=utcnow)
    updated_at = Column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class VideoEnhanceJob(Base):
    """
    Melhoria de um vídeo enviado pelo usuário.

    O vídeo vem pronto de fora (na prática, gerado no app do Gemini/Flow, que
    entrega 720p com bitrate baixo) e aqui passa pelo tratamento local: upscale
    para 1080p, interpolação se estiver abaixo do fps alvo, e reencode com
    bitrate limpo. Cada etapa é pulada quando a fonte já está no alvo.

    Pipeline de status:
      pending → processing → done | failed

    `status_detail` é o texto que a UI mostra durante as etapas ("fazendo
    upscale"); sem ele a tela fica parada num status só enquanto o FFmpeg roda.
    """

    __tablename__ = "video_enhance_jobs"

    id = Column(String, primary_key=True, default=uuid4_hex)
    original_filename = Column(String, nullable=True)   # como o usuário chamou
    source_video_path = Column(String, nullable=False)  # o arquivo enviado
    final_video_path = Column(String, nullable=True)    # depois do tratamento
    # Antes/depois, para a tela justificar o tratamento em vez de só afirmar.
    source_summary = Column(String, nullable=True)      # ex.: "720x1280 · 24fps · 1.9 Mbps"
    final_summary = Column(String, nullable=True)
    # Etapas que rodaram e as que foram dispensadas/falharam, JSON de listas.
    steps_json = Column(Text, nullable=True)
    status = Column(String, default="pending")  # pending|processing|done|failed
    status_detail = Column(String, nullable=True)
    error_message = Column(String, nullable=True)
    created_at = Column(DateTime(timezone=True), default=utcnow)
    updated_at = Column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class Clip(Base):
    __tablename__ = "clips"

    id = Column(String, primary_key=True, default=uuid4_hex)
    job_id = Column(String, ForeignKey("jobs.id"), nullable=False)
    start_time = Column(Float, nullable=False)
    end_time = Column(Float, nullable=False)
    duration = Column(Float, nullable=False)
    virality_score = Column(Float, nullable=False)  # 0-10, é o final_score/10
    # Eixos da rubrica (0-10 cada). Guardados individualmente porque o
    # cronograma escolhe o clip de cada horário por um eixo específico —
    # 07:00 pega o maior hook_score, 22:30 o maior loopability_score.
    hook_score = Column(Float, nullable=True)
    retention_score = Column(Float, nullable=True)
    shareability_score = Column(Float, nullable=True)
    loopability_score = Column(Float, nullable=True)
    comment_bait_score = Column(Float, nullable=True)
    verdict = Column(String, nullable=True)         # post | revisar_corte
    weak_points_json = Column(String, nullable=True)  # JSON array de trechos fracos
    trim_reason = Column(String, nullable=True)     # por que o corte é esse
    # Trechos costurados num clipe só, JSON [[ini,fim],...] (só Siege).
    # Nulo = clipe contínuo comum entre start_time e end_time.
    segments_json = Column(Text, nullable=True)
    hook = Column(String, nullable=True)
    reason = Column(String, nullable=True)
    tags_json = Column(String, nullable=True)       # JSON array de tags
    suggested_title = Column(String, nullable=True)
    transcript_excerpt = Column(Text, nullable=True)
    part_number = Column(Integer, nullable=True)    # 1, 2 (null se não dividido)
    parent_clip_id = Column(String, nullable=True)  # referência ao clip original se dividido
    subtitle_mode = Column(String, default="word_highlight")
    status = Column(String, default="processing")   # processing|ready|error
    file_path = Column(String, nullable=True)
    file_size_bytes = Column(Integer, nullable=True)
    created_at = Column(DateTime(timezone=True), default=utcnow)

    # ── Desempenho real depois de postado ─────────────────────────────────────
    # A nota é uma previsão; estes campos são o que aconteceu. Sem eles o
    # sistema não tem como saber que um 8.4 rendeu mal, e o few-shot dinâmico
    # (prompt_engine/) fica aprendendo só com rótulo manual. Nulo = ainda não
    # medido, que é diferente de zero.
    posted_at = Column(DateTime(timezone=True), nullable=True)
    views = Column(Integer, nullable=True)
    # Fração de quem chegou ao fim (0-1). É o sinal que o algoritmo mais pesa,
    # e o único que distingue "muita gente viu" de "muita gente ficou".
    completion_rate = Column(Float, nullable=True)
    likes = Column(Integer, nullable=True)
    comments = Column(Integer, nullable=True)
    shares = Column(Integer, nullable=True)
    # Quando os números acima foram coletados — views de um clipe de 3 dias e
    # de um de 3 meses não são comparáveis sem isto.
    metrics_at = Column(DateTime(timezone=True), nullable=True)

    job = relationship("Job", back_populates="clips")
