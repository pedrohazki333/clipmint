"""
PromptBuilder — monta o system prompt enriquecido com exemplos validados.

Lê os JSONs de prompt_engine/examples/validated/ e seleciona até 6 exemplos
priorizando:
  1. Performance mais alta (viral > muito_bom > bom)
  2. Diversidade de categorias — máximo 2 exemplos por tag primária
  3. Exemplos com campo "aprendizado" preenchido preferidos dentro do mesmo nível

Se a pasta validated/ estiver vazia, retorna apenas o core_prompt sem alteração.
"""

import json
import logging
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

_PERFORMANCE_RANK = {"viral": 0, "muito_bom": 1, "bom": 2}

_EXAMPLES_DIR = Path(__file__).parent / "examples" / "validated"
_CORE_PROMPT_PATH = Path(__file__).parent / "core_prompt.txt"


class PromptBuilder:
    """
    Constrói o system prompt final para o analyzer.py.

    Uso:
        builder = PromptBuilder()
        system_prompt = builder.build(min_duration=15, max_duration=90)
    """

    def build(
        self,
        min_duration: int = 15,
        max_duration: int = 90,
        nicho: Optional[str] = None,
        max_examples: int = 6,
        max_per_category: int = 2,
    ) -> str:
        """
        Retorna o system prompt com exemplos validados injetados ao final.

        Args:
            min_duration: Duração mínima de clip em segundos (repassado ao core_prompt).
            max_duration: Duração máxima de clip em segundos (repassado ao core_prompt).
            nicho: Filtro opcional de nicho (não implementado ainda, reservado para futuro).
            max_examples: Número máximo de exemplos a injetar (default: 6).
            max_per_category: Máximo de exemplos por tag primária (default: 2).

        Returns:
            String com o system prompt completo, pronto para envio ao Claude.
        """
        core = _CORE_PROMPT_PATH.read_text(encoding="utf-8").strip()
        core = core.format(min_duration=min_duration, max_duration=max_duration)

        examples = self._load_examples()
        if not examples:
            logger.debug("No validated examples found — using core prompt only.")
            return core

        selected = self._select_examples(examples, max_examples, max_per_category)
        if not selected:
            return core

        logger.info(f"Injecting {len(selected)} validated example(s) into system prompt.")
        return core + "\n\n" + self._format_section(selected)

    # ── Internal helpers ────────────────────────────────────────────────────────

    def _load_examples(self) -> list[dict]:
        """Carrega todos os JSONs válidos de examples/validated/."""
        if not _EXAMPLES_DIR.exists():
            return []

        examples = []
        for path in sorted(_EXAMPLES_DIR.glob("*.json")):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                examples.append(data)
            except (json.JSONDecodeError, OSError) as e:
                logger.warning(f"Skipping invalid example file {path.name}: {e}")

        return examples

    def _select_examples(
        self,
        examples: list[dict],
        max_examples: int,
        max_per_category: int,
    ) -> list[dict]:
        """
        Seleciona exemplos respeitando prioridade e diversidade de categorias.

        Critérios de ordenação (menor = melhor):
          (performance_rank, sem_aprendizado)
        """
        def sort_key(e: dict) -> tuple:
            perf = _PERFORMANCE_RANK.get(
                e.get("validation", {}).get("performance", "bom"), 2
            )
            has_aprendizado = 0 if e.get("validation", {}).get("aprendizado", "").strip() else 1
            return (perf, has_aprendizado)

        sorted_examples = sorted(examples, key=sort_key)

        selected: list[dict] = []
        category_counts: dict[str, int] = {}

        for ex in sorted_examples:
            if len(selected) >= max_examples:
                break

            tags: list[str] = ex.get("clip", {}).get("tags", [])
            primary_tag = tags[0] if tags else "other"

            if category_counts.get(primary_tag, 0) >= max_per_category:
                # Tenta a próxima tag disponível antes de descartar
                found_alt = False
                for tag in tags[1:]:
                    if category_counts.get(tag, 0) < max_per_category:
                        primary_tag = tag
                        found_alt = True
                        break
                if not found_alt:
                    continue

            selected.append(ex)
            category_counts[primary_tag] = category_counts.get(primary_tag, 0) + 1

        return selected

    def _format_section(self, examples: list[dict]) -> str:
        """Formata os exemplos selecionados como seção de texto para o prompt."""
        lines: list[str] = [
            "## VALIDATED EXAMPLES (Real clips that performed well)",
            "Use these as calibration references — pay attention to what makes each one work.",
            "",
        ]

        for i, ex in enumerate(examples, 1):
            v = ex.get("video", {})
            c = ex.get("clip", {})
            val = ex.get("validation", {})

            perf_label = val.get("performance", "bom").replace("_", " ").upper()
            lines.append(f"### Example {i} — {perf_label}")
            lines.append(f'- Video: "{v.get("title", "N/A")}" by {v.get("channel", "N/A")}')

            start = c.get("start", 0)
            end = c.get("end", 0)
            dur = c.get("duration", end - start)
            lines.append(f"- Clip: {start:.1f}s → {end:.1f}s ({dur:.0f}s)")
            lines.append(f"- Virality score: {c.get('virality_score', 0)}")
            lines.append(f'- Hook overlay: "{c.get("hook", "")}"')
            lines.append(f'- Opening phrase: "{c.get("opening_phrase", "")}"')

            tags = c.get("tags", [])
            if tags:
                lines.append(f"- Tags: {', '.join(tags)}")

            views = val.get("views")
            if views:
                lines.append(f"- Real-world views: {views:,}")

            aprendizado = val.get("aprendizado", "").strip()
            if aprendizado:
                lines.append(f"- Why it worked: {aprendizado}")

            lines.append("")

        return "\n".join(lines).rstrip()
