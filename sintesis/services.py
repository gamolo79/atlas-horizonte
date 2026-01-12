import logging
import os
from dataclasses import dataclass
from typing import Iterable, List, Sequence

from django.utils import timezone
from openai import OpenAI

from atlas_core.text_utils import normalize_name, tokenize
from monitor.services import parse_json_response


logger = logging.getLogger(__name__)


@dataclass
class ArticleProfile:
    article: object
    tokens: set
    central_idea: str
    labels: List[str]
    mentions: List[str]


def _tokenize_values(values: Iterable[str]) -> set:
    tokens = set()
    for value in values:
        if not value:
            continue
        tokens.update(tokenize(value))
    return tokens


def build_profile(article) -> ArticleProfile:
    classification = getattr(article, "classification", None)
    central_idea = getattr(classification, "central_idea", "") if classification else ""
    labels = list(getattr(classification, "labels_json", []) or [])
    mentions = []
    if classification:
        mentions = [mention.target_name for mention in classification.mentions.all()]
    tokens = _tokenize_values(
        [article.title, article.text[:500], central_idea, *labels, *mentions]
    )
    return ArticleProfile(
        article=article,
        tokens=tokens,
        central_idea=central_idea,
        labels=labels,
        mentions=mentions,
    )


def jaccard_similarity(tokens_a: set, tokens_b: set) -> float:
    if not tokens_a or not tokens_b:
        return 0.0
    intersection = tokens_a & tokens_b
    union = tokens_a | tokens_b
    if not union:
        return 0.0
    return len(intersection) / len(union)


def weighted_similarity(profile_a: ArticleProfile, group: dict) -> float:
    # Base token similarity (title + text)
    token_score = jaccard_similarity(profile_a.tokens, group["tokens"])
    
    # Entity similarity (mentions)
    mentions_a = set(profile_a.mentions)
    mentions_b = group["mentions"]
    entity_score = jaccard_similarity(mentions_a, mentions_b)
    
    # Label similarity
    labels_a = set(profile_a.labels)
    labels_b = group["labels"]
    label_score = jaccard_similarity(labels_a, labels_b)

    # Weighted average: Tokens (40%), Entities (40%), Labels (20%)
    # If central idea matches, we boost significantly in group_profiles
    return (token_score * 0.4) + (entity_score * 0.4) + (label_score * 0.2)


def group_profiles(profiles: Sequence[ArticleProfile], threshold: float = 0.25) -> List[dict]:
    groups: List[dict] = []
    
    # Sort profiles by date or importance if possible, here we just iterate
    for profile in profiles:
        best_group = None
        best_score = 0.0
        
        normalized_idea = normalize_name(profile.central_idea)

        for group in groups:
            # Check Central Idea Match Step
            if normalized_idea and normalized_idea == group["central_idea"]:
                # Strong match, boost score to very high
                score = 1.0 
            else:
                score = weighted_similarity(profile, group)

            if score > best_score:
                best_score = score
                best_group = group
        
        # Threshold Logic
        if best_group and best_score >= threshold:
            best_group["profiles"].append(profile)
            best_group["tokens"].update(profile.tokens)
            best_group["labels"].update(profile.labels)
            best_group["mentions"].update(profile.mentions)
            # Update central idea if empty in group
            if not best_group["central_idea"] and normalized_idea:
                best_group["central_idea"] = normalized_idea
        else:
            groups.append(
                {
                    "profiles": [profile],
                    "tokens": set(profile.tokens),
                    "central_idea": normalized_idea,
                    "labels": set(profile.labels),
                    "mentions": set(profile.mentions),
                }
            )
    return groups


def generate_story_text(group: dict) -> dict:
    api_key = os.getenv("OPENAI_API_KEY")
    project_id = os.getenv("OPENAI_PROJECT_ID")
    model_name = os.environ.get("OPENAI_MODEL", "gpt-4o-mini")
    if not api_key:
        return fallback_story_text(group)

    if api_key.startswith("sk-proj-") and not project_id:
        raise RuntimeError("OPENAI_PROJECT_ID es requerido para claves sk-proj-*.")

    client = OpenAI(api_key=api_key, project=project_id)
    profiles = group["profiles"]
    titles = [profile.article.title for profile in profiles[:6]]
    central_idea = profiles[0].central_idea if profiles else ""
    labels = list(group["labels"])[:8]
    mentions = list(group["mentions"])[:8]

    prompt = f"""
Eres un editor experto de noticias. Tu tarea es sintetizar este grupo de artículos en una historia cohesiva.

Instrucciones:
1. Analiza los titulares y la Idea Central.
2. Escribe un TÍTULO corto y atractivo (Mínimo 8 palabras, Máximo 14 palabras).
3. Escribe un RESUMEN que sintetice los hechos principales (Mínimo 20 palabras, Máximo 40 palabras).
4. El tono debe ser periodístico, neutral y directo.
5. Devuelve SOLO un objeto JSON válido.

Insumos:
- Idea central: {central_idea}
- Etiquetas IA: {", ".join(labels)}
- Menciones: {", ".join(mentions)}
- Titulares: {" | ".join(titles)}
- Fecha del reporte: {timezone.now().strftime("%d/%m/%Y")}

Schema JSON esperado:
{{
  "title": "string (10-14 palabras)",
  "summary": "string (20-40 palabras)"
}}
""".strip()

    response = client.chat.completions.create(
        model=model_name,
        messages=[
            {"role": "system", "content": "Eres un asistente que responde solo JSON válido."},
            {"role": "user", "content": prompt},
        ],
        temperature=0.2,
    )
    raw = response.choices[0].message.content or ""
    payload = parse_json_response(raw)
    title = payload.get("title", "")
    summary = payload.get("summary", "")
    
    # Fallback validation
    if not title or not summary:
        return fallback_story_text(group)
        
    return {"title": title.strip(), "summary": summary.strip()}


def fallback_story_text(group: dict) -> dict:
    profiles = group["profiles"]
    if not profiles:
        return {"title": "Síntesis sin artículos", "summary": "No hay notas asociadas."}
    first = profiles[0]
    title = first.article.title
    if len(title.split()) > 14:
        title = " ".join(title.split()[:14])
    summary = first.central_idea or first.article.text[:160]
    summary_words = summary.split()
    if len(summary_words) > 40:
        summary = " ".join(summary_words[:40])
    return {"title": title, "summary": summary}
