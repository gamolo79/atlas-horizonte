import logging
import os
from collections import Counter
from dataclasses import dataclass
from typing import Dict, Iterable, List, Sequence, Set, Tuple

from django.conf import settings
from django.utils import timezone
from openai import OpenAI

from atlas_core.text_utils import normalize_name, tokenize
from monitor.services import parse_json_response


logger = logging.getLogger(__name__)


@dataclass
class ArticleProfile:
    article: object
    tokens: set
    title_tokens: Set[str]
    idea_tokens: Set[str]
    label_tokens: Set[str]
    central_idea: str
    labels: List[str]
    mentions: List[str]
    entity_keys: Set[str]
    entity_names: Dict[str, str]


DEFAULT_TAG_BLACKLIST = {"seguridad", "gobierno", "queretaro"}
DEFAULT_TAG_STOPWORDS = {
    "a",
    "al",
    "con",
    "contra",
    "de",
    "del",
    "el",
    "en",
    "es",
    "la",
    "las",
    "los",
    "para",
    "por",
    "sin",
    "sobre",
    "un",
    "una",
    "y",
}


def _tokenize_values(values: Iterable[str]) -> set:
    tokens = set()
    for value in values:
        if not value:
            continue
        tokens.update(tokenize(value))
    return tokens


def _normalized_label_tokens(labels: Iterable[str]) -> Set[str]:
    stopwords = set(getattr(settings, "SINTESIS_TAG_STOPWORDS", DEFAULT_TAG_STOPWORDS))
    normalized: Set[str] = set()
    for label in labels:
        if not label:
            continue
        for token in tokenize(label):
            if token and token not in stopwords:
                normalized.add(token)
    return normalized


def _extract_entities(classification) -> Tuple[Set[str], Dict[str, str], List[str]]:
    entity_keys: Set[str] = set()
    entity_names: Dict[str, str] = {}
    mention_names: List[str] = []
    if not classification:
        return entity_keys, entity_names, mention_names
    for mention in classification.mentions.all():
        key = f"{mention.target_type}:{mention.target_id}"
        entity_keys.add(key)
        entity_names[key] = mention.target_name
        mention_names.append(mention.target_name)
    return entity_keys, entity_names, mention_names


def build_profile(article) -> ArticleProfile:
    classification = getattr(article, "classification", None)
    central_idea = getattr(classification, "central_idea", "") if classification else ""
    labels = list(getattr(classification, "labels_json", []) or [])
    entity_keys, entity_names, mentions = _extract_entities(classification)
    tokens = _tokenize_values(
        [article.title, article.text[:500], central_idea, *labels, *mentions]
    )
    title_tokens = set(tokenize(article.title or ""))
    idea_tokens = set(tokenize(central_idea))
    label_tokens = _normalized_label_tokens(labels)
    return ArticleProfile(
        article=article,
        tokens=tokens,
        title_tokens=title_tokens,
        idea_tokens=idea_tokens,
        label_tokens=label_tokens,
        central_idea=central_idea,
        labels=labels,
        mentions=mentions,
        entity_keys=entity_keys,
        entity_names=entity_names,
    )


def jaccard_similarity(tokens_a: set, tokens_b: set) -> float:
    if not tokens_a or not tokens_b:
        return 0.0
    intersection = tokens_a & tokens_b
    union = tokens_a | tokens_b
    if not union:
        return 0.0
    return len(intersection) / len(union)


def _tag_weights(profiles: Sequence[ArticleProfile]) -> Dict[str, float]:
    tag_counts: Counter[str] = Counter()
    for profile in profiles:
        tag_counts.update(profile.label_tokens)
    blacklist = set(getattr(settings, "SINTESIS_TAG_BLACKLIST", DEFAULT_TAG_BLACKLIST))
    weights: Dict[str, float] = {}
    for tag, count in tag_counts.items():
        weight = 1 / (1 + count)
        if tag in blacklist:
            weight *= 0.1
        weights[tag] = weight
    return weights


def _weighted_jaccard(tokens_a: Set[str], tokens_b: Set[str], weights: Dict[str, float]) -> float:
    if not tokens_a or not tokens_b:
        return 0.0
    union = tokens_a | tokens_b
    if not union:
        return 0.0
    intersection = tokens_a & tokens_b
    numerator = sum(weights.get(token, 0.0) for token in intersection)
    denominator = sum(weights.get(token, 0.0) for token in union)
    if not denominator:
        return 0.0
    return numerator / denominator


def _similarity_details(
    profile: ArticleProfile,
    group: dict,
    tag_weights: Dict[str, float],
) -> Tuple[float, Dict[str, float], Set[str], Set[str]]:
    entity_overlap = profile.entity_keys & group["entity_keys"]
    entity_score = jaccard_similarity(profile.entity_keys, group["entity_keys"])
    title_score = jaccard_similarity(profile.title_tokens, group["title_tokens"])
    idea_score = jaccard_similarity(profile.idea_tokens, group["idea_tokens"])
    tag_score = _weighted_jaccard(profile.label_tokens, group["label_tokens"], tag_weights)
    score = (entity_score * 0.45) + (title_score * 0.25) + (idea_score * 0.2) + (tag_score * 0.1)
    return (
        score,
        {
            "entity_score": entity_score,
            "title_score": title_score,
            "idea_score": idea_score,
            "tag_score": tag_score,
        },
        entity_overlap,
        profile.label_tokens & group["label_tokens"],
    )


def group_profiles(profiles: Sequence[ArticleProfile], threshold: float = 0.65) -> List[dict]:
    groups: List[dict] = []
    tag_weights = _tag_weights(profiles)
    title_gate = getattr(settings, "SINTESIS_TITLE_SIM_THRESHOLD", 0.55)
    idea_gate = getattr(settings, "SINTESIS_IDEA_SIM_THRESHOLD", 0.5)
    
    # Sort profiles by date or importance if possible, here we just iterate
    for profile in profiles:
        best_group = None
        best_score = 0.0
        best_signals: List[str] = []
        
        normalized_idea = normalize_name(profile.central_idea)

        for group in groups:
            score, details, entity_overlap, tag_overlap = _similarity_details(
                profile, group, tag_weights
            )
            if not score:
                continue

            if not entity_overlap and details["title_score"] < title_gate:
                if details["idea_score"] < idea_gate and len(tag_overlap) <= 1:
                    continue

            if score > best_score:
                best_score = score
                best_group = group
                best_signals = _build_signals(
                    profile,
                    group,
                    details,
                    entity_overlap,
                    tag_overlap,
                )
        
        # Threshold Logic
        if best_group and best_score >= threshold:
            best_group["profiles"].append(profile)
            best_group["tokens"].update(profile.tokens)
            best_group["labels"].update(profile.labels)
            best_group["mentions"].update(profile.mentions)
            best_group["title_tokens"].update(profile.title_tokens)
            best_group["idea_tokens"].update(profile.idea_tokens)
            best_group["label_tokens"].update(profile.label_tokens)
            best_group["entity_keys"].update(profile.entity_keys)
            best_group["entity_names"].update(profile.entity_names)
            best_group["signals"].update(best_signals)
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
                    "title_tokens": set(profile.title_tokens),
                    "idea_tokens": set(profile.idea_tokens),
                    "label_tokens": set(profile.label_tokens),
                    "entity_keys": set(profile.entity_keys),
                    "entity_names": dict(profile.entity_names),
                    "signals": Counter(),
                }
            )
    for group in groups:
        group["signals"] = [signal for signal, _count in group["signals"].most_common(3)]
    return groups


def _build_signals(
    profile: ArticleProfile,
    group: dict,
    details: Dict[str, float],
    entity_overlap: Set[str],
    tag_overlap: Set[str],
) -> List[str]:
    signals: List[str] = []
    title_gate = getattr(settings, "SINTESIS_TITLE_SIM_THRESHOLD", 0.55)
    idea_gate = getattr(settings, "SINTESIS_IDEA_SIM_THRESHOLD", 0.5)
    if entity_overlap:
        key = next(iter(entity_overlap))
        entity_name = group["entity_names"].get(key) or profile.entity_names.get(key) or "entidad"
        signals.append(f"Entidad compartida: {entity_name}")
    if details["title_score"] >= title_gate:
        signals.append(f"Título similar: {details['title_score']:.0%}")
    if details["idea_score"] >= idea_gate:
        signals.append(f"Idea central similar: {details['idea_score']:.0%}")
    if tag_overlap:
        signals.append(f"Etiquetas coinciden: {len(tag_overlap)}")
    return signals


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
