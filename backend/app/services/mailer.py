"""
Envio de e-mail transacional.

**Só a recuperação de senha usa isto**, e é de propósito: e-mail é uma dívida
de manutenção (domínio, SPF, DKIM, reputação, bounce) e só vale a pena onde
não há alternativa. Recuperar senha é o único lugar do ClipMint onde não há:
é a única porta de volta para uma conta com créditos comprados dentro.

**SMTP, e não a API de um provedor.** Resend, SendGrid e Amazon SES falam SMTP;
amarrar o código à API de um deles transformaria "trocar de provedor" em
reescrever o serviço, e provedor de e-mail se troca por preço e por reputação
de IP, não por gosto.

**Roda em thread.** `smtplib` é síncrono e uma conexão SMTP leva de centenas de
milissegundos a segundos — no laço de eventos isso trava TODAS as requisições do
servidor enquanto o provedor não responde.
"""

import asyncio
import logging
import smtplib
from email.message import EmailMessage

from app.config import settings

logger = logging.getLogger(__name__)


def enabled() -> bool:
    """O servidor consegue mandar e-mail?

    Sem host ou sem remetente não adianta tentar: a rota que depende disto
    recusa na porta, em vez de aceitar o pedido e perdê-lo em silêncio.
    """
    return bool(settings.smtp_host and settings.smtp_from)


def _entregar(to: str, subject: str, body: str) -> None:
    """A parte bloqueante. Chamada por `send` dentro de uma thread."""
    msg = EmailMessage()
    msg["From"] = settings.smtp_from
    msg["To"] = to
    msg["Subject"] = subject
    msg.set_content(body)

    # 465 é SMTPS (TLS desde o handshake); as demais portas começam em claro e
    # sobem para TLS com STARTTLS. Escolher pela porta evita mais uma variável
    # de configuração para alguém errar.
    if settings.smtp_port == 465:
        with smtplib.SMTP_SSL(settings.smtp_host, settings.smtp_port, timeout=20) as s:
            if settings.smtp_user:
                s.login(settings.smtp_user, settings.smtp_password)
            s.send_message(msg)
    else:
        with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=20) as s:
            s.starttls()
            if settings.smtp_user:
                s.login(settings.smtp_user, settings.smtp_password)
            s.send_message(msg)


async def send(to: str, subject: str, body: str) -> None:
    """Manda o e-mail. Levanta em caso de falha — quem chama decide o que fazer.

    Não engole exceção aqui de propósito: na recuperação de senha, um envio que
    falhou calado vira um usuário esperando para sempre um e-mail que não vem.
    """
    if not enabled():
        raise RuntimeError("SMTP não configurado")
    await asyncio.to_thread(_entregar, to, subject, body)
    logger.info("E-mail enviado para %s: %s", to, subject)
