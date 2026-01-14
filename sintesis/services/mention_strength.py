from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterable, List

from atlas_core.text_utils import normalize_name


ACTION_VERBS = {
    "anunció",
    "aseguró",
    "declaró",
    "dijo",
    "explicó",
    "informó",
    "investigó",
    "lanzó",
    "ordenó",
    "presentó",
    "prometió",
    "publicó",
    "reveló",
    "solicitó",
    "suspendió",
}


@dataclass
class MentionStrength:
    target_type: str
    target_id: int
    target_name: str
    strength: str
    positions: dict


def classify_mentions(article, mentions: Iterable) -> List[MentionStrength]:
    title_text = normalize_name(article.title or "")
    body_text = normalize_name(article.text or "")
    words = body_text.split()
    lead_text = " ".join(words[:50])
    results: List[MentionStrength] = []

    for mention in mentions:
        name = mention.target_name or ""
        normalized = normalize_name(name)
        if not normalized:
            continue
        title_hit = normalized in title_text
        lead_hit = normalized in lead_text
        occurrences = len(re.findall(re.escape(normalized), body_text))
        near_action = _near_action_verb(body_text, normalized)

        strength = "weak"
        if title_hit or lead_hit or occurrences >= 2 or near_action:
            strength = "strong"

        results.append(
            MentionStrength(
                target_type=mention.target_type,
                target_id=mention.target_id,
                target_name=mention.target_name,
                strength=strength,
                positions={
                    "title": title_hit,
                    "lead": lead_hit,
                    "occurrences": occurrences,
                    "near_action": near_action,
                },
            )
        )
    return results


def _near_action_verb(text: str, entity: str, window: int = 50) -> bool:
    if not entity:
        return False
    index = text.find(entity)
    if index == -1:
        return False
    start = max(index - window, 0)
    end = min(index + window, len(text))
    snippet = text[start:end]
    for verb in ACTION_VERBS:
        if verb in snippet:
            return True
    return False
