"""
A triagem do relato de enquadramento: o print está mesmo ruim?

**Por que triar.** Destravar a correção custa CPU do servidor — servir quadros do
vídeo de origem e re-renderizar o clipe. Um botão livre viraria desperdício
garantido: pedir correção em todo job sairia de graça para quem pede.

**Por que não confiar só na descrição.** "Ficou ruim" não distingue enquadramento
errado de gosto pessoal, e ninguém escreve laudo. O print mostra.

**O viés é assumido, e é para APROVAR na dúvida.** Recusar um problema real
significa um cliente que pagou, recebeu clipe torto e ouviu "está bom". Aprovar
um clipe que estava bom custa um render. O erro caro é o primeiro, então o
prompt manda aprovar quando não tiver certeza — a triagem existe para barrar
pedido em lote, não para discutir com quem pagou.
"""

import base64
import json
import logging

import anthropic

from app.config import settings

logger = logging.getLogger(__name__)

#: O que conta como enquadramento errado. Lista fechada de propósito: sem ela o
#: modelo julga estética ("o corte ficou sem graça"), que não é o que o corretor
#: conserta — ele só move a caixa da cam.
_PERGUNTA = """Esta é uma captura de tela de um clipe vertical (9:16) gerado
automaticamente. O clipe tem um painel superior que deveria mostrar APENAS a
webcam do streamer (o rosto dele), e um painel inferior com a gameplay.

O usuário relatou este problema com o enquadramento do painel de cima:
"{descricao}"

Responda se o painel SUPERIOR tem algum destes defeitos concretos:
- aparece gameplay, cenário do jogo ou HUD dentro dele (deveria ser só a webcam);
- a cabeça ou o rosto do streamer está cortado pela borda;
- o rosto aparece minúsculo, com muito espaço vazio em volta;
- o painel mostra outra coisa que não a webcam.

NÃO conte como defeito: a qualidade do vídeo, o corte ter ficado sem graça, a
legenda, as cores, o banner ou a escolha do trecho. O corretor só move a caixa
da webcam — não conserta nada disso.

Na dúvida, responda que está ruim: recusar um problema real é pior que liberar
uma correção desnecessária.

Responda APENAS um JSON:
{{"ruim": true|false, "motivo": "uma frase curta, em português, dizendo o que
você viu no painel de cima"}}"""


async def avaliar(screenshot: bytes, media_type: str, descricao: str) -> tuple[bool, str]:
    """(está ruim?, o que a visão viu).

    Nunca levanta. Falha de rede, chave ou resposta ilegível **aprovam** — a
    triagem é uma economia de CPU, e derrubar o pedido de quem pagou por causa
    de um erro nosso troca uma economia pequena por um cliente irritado.
    """
    if not settings.anthropic_api_key:
        return True, "Triagem indisponível; correção liberada."

    client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)
    try:
        message = await client.messages.create(
            model=settings.claude_vision_model,
            max_tokens=300,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "image",
                            "source": {
                                "type": "base64",
                                "media_type": media_type,
                                "data": base64.standard_b64encode(screenshot).decode(),
                            },
                        },
                        {
                            "type": "text",
                            "text": _PERGUNTA.format(descricao=descricao[:500]),
                        },
                    ],
                }
            ],
        )
        bruto = message.content[0].text.strip()
        if bruto.startswith("```"):
            linhas = bruto.split("\n")
            bruto = "\n".join(linhas[1:-1] if linhas[-1].strip() == "```" else linhas[1:])
        dados = json.loads(bruto)
        ruim = bool(dados.get("ruim"))
        motivo = str(dados.get("motivo") or "").strip()
        logger.info("Triagem do enquadramento: ruim=%s — %s", ruim, motivo)
        return ruim, motivo or ("Enquadramento com defeito." if ruim else "O painel de cima parece correto.")
    except Exception:  # noqa: BLE001
        logger.exception("Falha ao triar o print do enquadramento — liberando")
        return True, "Não consegui analisar o print agora; correção liberada."
