from __future__ import annotations

import hashlib
import importlib.util
import logging
import os
from typing import Iterable, List, Sequence

from django.conf import settings

from atlas_core.text_utils import normalize_name

logger = logging.getLogger(__name__)


def build_canonical_text(article, labels: Iterable[str], entities: Iterable[str]) -> str:
    title = (article.title or "").strip()
    idea = getattr(getattr(article, "classification", None), "central_idea", "") or ""
    labels_text = ", ".join([label for label in labels if label])[:240]
    entities_text = ", ".join([entity for entity in entities if entity])[:240]
    raw = f"{title} | {idea} | {labels_text} | {entities_text}"
    normalized = " ".join(raw.split())
    trimmed = normalized[:900]
    return trimmed


def canonical_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def canonical_keywords(values: Iterable[str]) -> list[str]:
    seen = set()
    keywords = []
    for value in values:
        normalized = normalize_name(value or "")
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        keywords.append(normalized)
    return keywords


def compute_embedding(text: str) -> List[float]:
    api_key = os.getenv("OPENAI_API_KEY")
    project_id = os.getenv("OPENAI_PROJECT_ID")
    model_name = os.environ.get("OPENAI_EMBEDDING_MODEL", "text-embedding-3-small")
    if not api_key:
        logger.info("OPENAI_API_KEY not set; skipping embedding generation.")
        return []

    if api_key.startswith("sk-proj-") and not project_id:
        raise RuntimeError("OPENAI_PROJECT_ID es requerido para claves sk-proj-*.")

    from openai import OpenAI

    client = OpenAI(api_key=api_key, project=project_id)
    response = client.embeddings.create(model=model_name, input=text)
    embedding = response.data[0].embedding or []
    return list(embedding)


def cosine_similarity(vec_a: Iterable[float], vec_b: Iterable[float]) -> float:
    a_list = list(vec_a)
    b_list = list(vec_b)
    if not a_list or not b_list or len(a_list) != len(b_list):
        return 0.0
    dot = sum(a * b for a, b in zip(a_list, b_list))
    norm_a = sum(a * a for a in a_list) ** 0.5
    norm_b = sum(b * b for b in b_list) ** 0.5
    if not norm_a or not norm_b:
        return 0.0
    return dot / (norm_a * norm_b)


def nearest_embeddings(
    target: Sequence[float],
    candidates: Iterable[Sequence[float]],
    top_k: int = 5,
) -> list[tuple[int, float]]:
    scored = []
    for idx, candidate in enumerate(candidates):
        score = cosine_similarity(target, candidate)
        scored.append((idx, score))
    scored.sort(key=lambda item: item[1], reverse=True)
    return scored[:top_k]


def pgvector_enabled() -> bool:
    if not getattr(settings, "SINTESIS_ENABLE_PGVECTOR", False):
        return False
    return importlib.util.find_spec("pgvector") is not None
