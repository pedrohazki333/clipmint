"""
Onde o job está agora — o número que move a barra da tela.

**Por que existe.** A tela sabia só em que ETAPA o job estava, e etapa é uma
informação grossa demais: "gerando clipes" durou 12 minutos no maior job medido
aqui, e durante esses 12 minutos a barra não tinha o que dizer. O resultado era
uma barra parada, que é pior que barra nenhuma — ela afirma que nada está
acontecendo enquanto o servidor trabalha.

**De onde vem o número.** De eventos reais, sempre:

- download: bytes recebidos / bytes totais, direto do yt-dlp;
- transcrição: envio do arquivo e volta da API;
- análise: os quatro passos que ela de fato executa, na ordem em que executa;
- clipes: o clipe N de M, e dentro dele o passo do render que está rodando.

**O par `pct` e `ate`.** Alguns passos não têm fração nenhuma para medir — a
chamada ao Claude devolve tudo de uma vez, e a AssemblyAI só responde "ainda
processando". Para esses, o servidor manda dois números: onde ele está de
verdade (`pct`) e onde o passo atual termina (`ate`). A tela desliza devagar de
um para o outro e PARA antes de chegar; quando o evento real acontece, o `pct`
salta para o valor verdadeiro. Assim a barra nunca mente sobre o que já
aconteceu, nunca anda para trás e nunca fica congelada.

**Por que na memória e não no banco.** O pipeline roda no mesmo processo da API
(BackgroundTasks, sem Celery), então um dicionário basta e evita uma escrita no
banco por segundo por job. Reiniciar o servidor esvazia isto — e é o
comportamento certo: um job que sobreviveu ao reinício não tem progresso a
relatar, e a tela cai no que ela sempre soube, a etapa atual.

Os pesos de cada etapa saíram de medição, não de chute: as marcas de
`stage_log` dos jobs reais deste servidor (5 jobs, vídeos de 5 min a 56 min)
deram mediana de 21s no download, 18s na transcrição, 80s na análise e 280s no
corte. O download levou de 14s a 641s no mesmo conjunto — é a etapa mais
imprevisível, e por isso ganha uma faixa maior do que a mediana pediria: ela é
uma das duas que têm fração real para relatar, então quanto mais barra ela
ocupa, mais tempo a barra passa se movendo de verdade.
"""

import logging
import threading
from dataclasses import dataclass
from typing import Iterator

logger = logging.getLogger(__name__)

#: Quanto da barra cabe a cada etapa. Soma 100.
PESOS: dict[str, float] = {
    "downloading": 15.0,
    "transcribing": 8.0,
    "analyzing": 22.0,
    "clipping": 55.0,
}

#: Onde cada etapa começa na barra.
_BASE: dict[str, float] = {}
_acumulado = 0.0
for _etapa in ("downloading", "transcribing", "analyzing", "clipping"):
    _BASE[_etapa] = _acumulado
    _acumulado += PESOS[_etapa]


@dataclass(frozen=True)
class Progresso:
    #: 0-100. O que já aconteceu de verdade.
    pct: float
    #: 0-100. Onde o passo atual termina — o teto do deslize da tela.
    ate: float
    #: O que está acontecendo agora, em uma linha, para a pessoa ler.
    nota: str


# O dicionário é lido pela API e escrito pelo pipeline (e, no download, por uma
# thread do yt-dlp). O lock protege a troca; cada valor é imutável, então quem
# leu não vê um registro pela metade.
_LOCK = threading.Lock()
_ESTADO: dict[str, Progresso] = {}


def _clamp(v: float, lo: float = 0.0, hi: float = 100.0) -> float:
    return max(lo, min(hi, v))


def report(job_id: str, etapa: str, fracao: float, nota: str, ate: float | None = None) -> None:
    """
    Registra onde o job está.

    `fracao` é 0-1 DENTRO da etapa; `ate` também, e é o fim do passo atual
    (omitido, vale a própria fração — passo sem deslize).

    Nunca anda para trás: um relato atrasado de uma thread do download não pode
    puxar a barra de volta depois que a etapa seguinte já começou.
    """
    base, peso = _BASE.get(etapa), PESOS.get(etapa)
    if base is None or peso is None:
        return

    pct = _clamp(base + peso * _clamp(fracao, 0.0, 1.0))
    teto = _clamp(base + peso * _clamp(ate if ate is not None else fracao, 0.0, 1.0))

    with _LOCK:
        anterior = _ESTADO.get(job_id)
        if anterior and anterior.pct > pct:
            # Relato fora de ordem: mantém a posição, mas aceita a nota nova
            # se ela vier de um passo mais adiantado.
            return
        _ESTADO[job_id] = Progresso(pct=pct, ate=max(teto, pct), nota=nota)


def get(job_id: str) -> Progresso | None:
    with _LOCK:
        return _ESTADO.get(job_id)


def clear(job_id: str) -> None:
    """O job terminou (ou morreu). Sem isto o dicionário cresceria para sempre."""
    with _LOCK:
        _ESTADO.pop(job_id, None)


#: O que dizer quando não há relato nenhum — job retomado depois de um
#: reinício, ou etapa que ainda não chamou `report`. A barra fica no começo da
#: etapa e desliza até o fim dela, que é a única coisa que se sabe ali.
_NOTA_DA_ETAPA = {
    "queued": "Na fila, esperando a vez",
    "downloading": "Baixando o vídeo do YouTube",
    "transcribing": "Transcrevendo a fala do vídeo",
    "analyzing": "Analisando o vídeo atrás dos melhores trechos",
    "clipping": "Montando os clipes verticais",
}


def para_etapa(etapa: str) -> Progresso:
    """
    O progresso derivado só da etapa — o piso, quando não há relato.

    Mora aqui, e não na tela, porque os pesos moram aqui: duas cópias da mesma
    tabela divergiriam no primeiro ajuste, e a barra passaria a andar diferente
    conforme o dado viesse do registro ou da etapa.
    """
    if etapa == "done":
        return Progresso(pct=100.0, ate=100.0, nota="Concluído")
    if etapa not in _BASE:
        return Progresso(pct=0.0, ate=PESOS["downloading"], nota=_NOTA_DA_ETAPA.get(etapa, ""))
    base = _BASE[etapa]
    return Progresso(
        pct=base, ate=base + PESOS[etapa], nota=_NOTA_DA_ETAPA.get(etapa, "")
    )


def atual(job_id: str, etapa: str) -> Progresso:
    """O relato de verdade, se houver; senão o piso da etapa."""
    relato = get(job_id)
    if relato is None:
        return para_etapa(etapa)
    # Um relato antigo (de antes de a etapa virar) não pode segurar a barra
    # atrás de onde a etapa já garante que ela está.
    piso = para_etapa(etapa)
    if relato.pct < piso.pct:
        return piso
    return relato


def por_item(indice: int, total: int, dentro: float = 0.0) -> float:
    """
    Fração da etapa para o item `indice` de `total`, mais o avanço dentro dele.

    É o que transforma "clipe 3 de 5, na metade do render" em um número: cada
    clipe tem uma faixa igual da etapa, e `dentro` anda dessa faixa.
    """
    if total <= 0:
        return 0.0
    largura = 1.0 / total
    return _clamp(indice * largura + largura * _clamp(dentro, 0.0, 1.0), 0.0, 1.0)


def faixas_de_item(indice: int, total: int) -> Iterator[float]:
    """Começo e fim da faixa de um item — açúcar para `report(..., ate=...)`."""
    yield por_item(indice, total)
    yield por_item(indice + 1, total)
