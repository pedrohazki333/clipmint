"""
Traduz a falha técnica na frase que o usuário lê.

O pipeline gravava `str(e)` direto no `error_message` do job, e era isso que
aparecia na tela: 2.000 caracteres de stderr do FFmpeg, ou
`ERROR: [youtube] xxx: Private video. Sign in if you've been granted access...`
em inglês. Some duas coisas de uma vez — o usuário não entende o que aconteceu,
e o interior do sistema vaza para fora.

O detalhe técnico não se perde: continua inteiro no log, que é onde ele serve
para alguma coisa. Aqui fica só o que ajuda quem está olhando a tela a decidir
o que fazer em seguida.

Regra ao acrescentar um caso: a frase tem que dizer o que aconteceu E o que
fazer. "Falha no download" não passa; "o vídeo é privado, então não há como
baixá-lo" passa.
"""

import logging

logger = logging.getLogger(__name__)

#: (trecho procurado na mensagem original, frase mostrada ao usuário).
#: A ordem importa: o primeiro trecho que casar vence, então os casos
#: específicos vêm antes dos genéricos.
_TRADUCOES: tuple[tuple[str, str], ...] = (
    # ── yt-dlp: o vídeo em si é o problema ────────────────────────────────────
    (
        "private video",
        "Este vídeo é privado. Só o dono pode liberá-lo — não há como baixá-lo.",
    ),
    (
        "video unavailable",
        "O vídeo não está mais disponível no YouTube (removido ou tornado privado).",
    ),
    (
        "removed by the uploader",
        "O vídeo foi removido pelo canal que o publicou.",
    ),
    (
        "account associated with this video has been terminated",
        "O canal que publicou este vídeo foi encerrado, e o vídeo foi junto.",
    ),
    (
        "sign in to confirm your age",
        "O vídeo tem restrição de idade e exige login no YouTube para ser baixado.",
    ),
    (
        "members-only",
        "Este vídeo é exclusivo para membros do canal.",
    ),
    (
        "join this channel",
        "Este vídeo é exclusivo para membros do canal.",
    ),
    (
        "is not available in your country",
        "O YouTube bloqueia este vídeo na região onde o servidor está.",
    ),
    (
        "drm protected",
        "O vídeo é protegido por DRM e não pode ser baixado.",
    ),
    (
        "incomplete youtube id",
        "O link está incompleto: falta o identificador do vídeo depois da barra.",
    ),
    (
        "unsupported url",
        "O link não é de um vídeo do YouTube que dê para baixar.",
    ),
    (
        "requested format is not available",
        "O YouTube não ofereceu nenhum formato de vídeo que sirva para este corte.",
    ),
    # ── yt-dlp: o problema é a rede ou o bloqueio temporário ──────────────────
    (
        "http error 403",
        "O YouTube recusou o download depois de várias tentativas. Costuma passar "
        "sozinho em alguns minutos — use 'Retomar'. Se insistir, atualize o "
        "yt-dlp com `make update-ytdlp`.",
    ),
    (
        "unable to download",
        "A conexão com o YouTube falhou durante o download. Use 'Retomar' para "
        "continuar de onde parou.",
    ),
    # ── Nossos próprios limites ───────────────────────────────────────────────
    (
        "passou de",  # FFmpegTimeout
        "O processamento de vídeo travou e foi abortado por tempo. Use 'Retomar' "
        "— o que já ficou pronto é aproveitado.",
    ),
    # ── Claude / AssemblyAI ───────────────────────────────────────────────────
    (
        "resposta cortada",  # teto de max_tokens (ver services/analyzer.py)
        "A análise devolveu uma resposta longa demais e veio cortada. Use "
        "'Retomar' para tentar de novo.",
    ),
    (
        "invalid json",
        "A análise devolveu uma resposta em formato inesperado. Use 'Retomar' "
        "para tentar de novo.",
    ),
    (
        "rate_limit",
        "O limite de uso da API de análise foi atingido. Espere alguns minutos e "
        "use 'Retomar'.",
    ),
    (
        "overloaded",
        "A API de análise está sobrecarregada no momento. Espere alguns minutos "
        "e use 'Retomar'.",
    ),
    (
        "authentication",
        "A chave de API não foi aceita. Confira as credenciais no .env do servidor.",
    ),
    (
        # ANTES de "assemblyai error": a mensagem do envio contém as duas
        # palavras, e a primeira regra que casa é a que vale. Invertendo a
        # ordem, o envio recairia na mensagem genérica de transcrição.
        "assemblyai upload error",
        "Não conseguimos enviar o áudio para a transcrição — o serviço recusou "
        "o arquivo. Use 'Retomar': o vídeo já baixado é reaproveitado.",
    ),
    (
        "assemblyai error",
        "A transcrição falhou no serviço externo. Use 'Retomar' para tentar de novo.",
    ),
    # ── Disco ─────────────────────────────────────────────────────────────────
    (
        "no space left on device",
        "O servidor ficou sem espaço em disco. Libere espaço e use 'Retomar'.",
    ),
)

#: Quando nada casa. Genérica de propósito: chutar uma causa errada é pior que
#: admitir que o detalhe está no log.
_FALLBACK = (
    "O processamento falhou por um erro inesperado. O detalhe técnico está no "
    "log do servidor. Use 'Retomar' para tentar de novo."
)

#: Erros nossos, escritos em português para serem lidos por quem usa. Passam
#: inteiros, sem tradução — traduzir de novo só apagaria a explicação boa.
_MENSAGENS_PRONTAS = (
    "MediaIntegrityError",
    "JobDeleted",
)


def user_message(exc: BaseException) -> str:
    """A frase que vai para o `error_message` do job."""
    original = str(exc)

    if type(exc).__name__ in _MENSAGENS_PRONTAS:
        return original

    lowered = original.lower()
    for trecho, frase in _TRADUCOES:
        if trecho in lowered:
            return frase

    logger.warning(
        f"Erro sem tradução ({type(exc).__name__}): {original[:300]} — "
        f"vale acrescentar um caso em app/errors.py se ele se repetir"
    )
    return _FALLBACK
