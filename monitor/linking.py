import json
import logging
import re

from django.db import transaction

from atlas_core.text_utils import normalize_name, tokenize
from monitor.models import (
    ArticleEntity,
    EntityLink,
    Mention,
    PersonaAlias,
    InstitucionAlias,
)
from redpolitica.models import Cargo, Institucion, Persona

LOGGER = logging.getLogger(__name__)

CONTEXT_KEYWORDS = {
    "gobernador": {"cargo": "gobernador"},
    "senador": {"cargo": "senador"},
    "diputado": {"cargo": "diputado"},
    "alcalde": {"cargo": "alcalde"},
    "presidente municipal": {"cargo": "presidente municipal"},
}

MENTION_STOP_WORDS = {
    "a",
    "al",
    "con",
    "de",
    "del",
    "el",
    "en",
    "la",
    "las",
    "lo",
    "los",
    "o",
    "para",
    "por",
    "que",
    "se",
    "sin",
    "su",
    "sus",
    "un",
    "una",
    "y",
}

BASE_SCORES = {
    "exact_name": 0.95,
    "exact_alias": 0.90,
    "surname_unique": 0.78,
    "surname_non_unique": 0.55,
    "partial": 0.40,
}

STATUS_THRESHOLDS = {
    "linked": 0.85,
    "proposed": 0.60,
}


AI_NER_MAX_ENTITIES = 40


def build_article_text(article, max_chars=8000):
    text = "\n".join(
        [
            article.title or "",
            getattr(article, "lead", "") or "",
            getattr(article, "body_text", "") or "",
        ]
    ).strip()
    if max_chars and len(text) > max_chars:
        return text[:max_chars]
    return text


def extract_mentions(article, method="alias_regex", window_size=200):
    normalized_text = build_article_text(article, max_chars=None)
    personas = list(PersonaAlias.objects.select_related("persona").all())
    instituciones = list(InstitucionAlias.objects.select_related("institucion").all())

    persona_entries = _build_entries_for_aliases(personas, Persona.objects.only("id", "nombre_completo"))
    institucion_entries = _build_entries_for_aliases(instituciones, Institucion.objects.only("id", "nombre"))

    created_mentions = 0
    for kind, entries in [
        (Mention.EntityKind.PERSON, persona_entries),
        (Mention.EntityKind.ORG, institucion_entries),
    ]:
        alias_map, regex = _build_alias_regex(entries)
        if not regex:
            continue
        for match in regex.finditer(normalized_text):
            surface = match.group(0)
            if _should_skip_surface(surface):
                continue
            span_start = match.start()
            span_end = match.end()
            context_start = max(span_start - window_size // 2, 0)
            context_end = min(span_end + window_size // 2, len(normalized_text))
            context_window = normalized_text[context_start:context_end]
            normalized_surface = normalize_name(surface)
            mention, created = Mention.objects.get_or_create(
                article=article,
                entity_kind=kind,
                span_start=span_start,
                span_end=span_end,
                normalized_surface=normalized_surface,
                defaults={
                    "surface": surface,
                    "context_window": context_window,
                    "method": method,
                },
            )
            if created:
                created_mentions += 1
            elif mention.surface != surface or mention.context_window != context_window:
                mention.surface = surface
                mention.context_window = context_window
                mention.method = method
                mention.save(update_fields=["surface", "context_window", "method", "normalized_surface"])
    return created_mentions


def extract_mentions_ai(
    article,
    client,
    model="gpt-4o-mini",
    max_entities=AI_NER_MAX_ENTITIES,
    method="ai_ner",
    window_size=240,
):
    text = build_article_text(article, max_chars=12000)
    if not text:
        return [], 0, None
    prompt = (
        "Extrae entidades PERSON y ORG del texto (title + lead + body). "
        "Responde SOLO JSON válido con llave entities (lista). "
        "Cada entity: surface, kind (PERSON u ORG). "
        f"Máximo {max_entities} entidades distintas."
        f"\n\nTexto:\n{text}"
    )
    try:
        response = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": "Eres un extractor NER. Responde SOLO JSON."},
                {"role": "user", "content": prompt},
            ],
            temperature=0.2,
            response_format={"type": "json_object"},
        )
    except Exception as exc:
        LOGGER.warning("Error OpenAI (NER): %s", exc)
        return [], 0, "ai_error"

    content = response.choices[0].message.content
    try:
        result = json.loads(content)
    except json.JSONDecodeError:
        LOGGER.warning("JSON inválido en respuesta NER IA.")
        return [], 0, "invalid_json"

    entities = result.get("entities") if isinstance(result, dict) else None
    if not isinstance(entities, list):
        LOGGER.warning("Respuesta NER IA sin lista de entidades.")
        return [], 0, "invalid_payload"

    created_mentions = 0
    mentions = []
    for entry in entities[:max_entities]:
        if not isinstance(entry, dict):
            continue
        surface = (entry.get("surface") or entry.get("text") or entry.get("name") or "").strip()
        if _should_skip_surface(surface):
            continue
        kind_raw = (entry.get("kind") or entry.get("type") or "").strip().upper()
        if kind_raw in ("PERSON", "PER"):
            kind = Mention.EntityKind.PERSON
        elif kind_raw in ("ORG", "ORGANIZATION", "INSTITUTION"):
            kind = Mention.EntityKind.ORG
        else:
            continue
        span_start, span_end = _find_surface_span(surface, text)
        context_window = ""
        if span_start is not None and span_end is not None:
            context_start = max(span_start - window_size // 2, 0)
            context_end = min(span_end + window_size // 2, len(text))
            context_window = text[context_start:context_end]
        mention, created = Mention.objects.get_or_create(
            article=article,
            entity_kind=kind,
            span_start=span_start,
            span_end=span_end,
            normalized_surface=normalize_name(surface),
            defaults={
                "surface": surface,
                "context_window": context_window,
                "method": method,
            },
        )
        if created:
            created_mentions += 1
        elif mention.surface != surface or mention.context_window != context_window or mention.method != method:
            mention.surface = surface
            mention.context_window = context_window
            mention.method = method
            mention.save(update_fields=["surface", "context_window", "method", "normalized_surface"])
        mentions.append(mention)
    return mentions, created_mentions, None


def retrieve_candidates(mention, limit=10, scope=None):
    normalized = mention.normalized_surface
    tokens = tokenize(normalized)
    candidates = []

    if mention.entity_kind == Mention.EntityKind.PERSON:
        qs_persona = Persona.objects.all()
        if scope and scope.get("personas"):
            qs_persona = qs_persona.filter(id__in=scope["personas"])

        exact_personas = qs_persona.filter(nombre_normalizado=normalized)
        candidates.extend(
            _candidate_dict("PERSON", persona, "exact_name", normalized)
            for persona in exact_personas
        )

        alias_qs = PersonaAlias.objects.filter(alias_normalizado=normalized)
        if scope and scope.get("personas"):
            alias_qs = alias_qs.filter(persona_id__in=scope["personas"])
        candidates.extend(
            _candidate_dict("PERSON", alias.persona, "exact_alias", alias.alias_normalizado)
            for alias in alias_qs.select_related("persona")
        )

        if len(tokens) == 1:
            surname = tokens[0]
            surname_matches = [
                persona
                for persona in qs_persona.filter(nombre_normalizado__contains=surname)
                if surname in tokenize(persona.nombre_normalizado)
            ]
            match_type = "surname_unique" if len(surname_matches) == 1 else "surname_non_unique"
            candidates.extend(
                _candidate_dict("PERSON", persona, match_type, surname)
                for persona in surname_matches
            )

        if not candidates and len(tokens) > 1:
            partial_matches = [
                persona
                for persona in qs_persona.filter(nombre_normalizado__contains=normalized)
            ]
            candidates.extend(
                _candidate_dict("PERSON", persona, "partial", normalized)
                for persona in partial_matches
            )

    elif mention.entity_kind == Mention.EntityKind.ORG:
        qs_inst = Institucion.objects.all()
        if scope and scope.get("instituciones"):
            qs_inst = qs_inst.filter(id__in=scope["instituciones"])

        exact_inst = qs_inst.filter(nombre_normalizado=normalized)
        candidates.extend(
            _candidate_dict("INSTITUTION", inst, "exact_name", normalized)
            for inst in exact_inst
        )

        alias_qs = InstitucionAlias.objects.filter(alias_normalizado=normalized)
        if scope and scope.get("instituciones"):
            alias_qs = alias_qs.filter(institucion_id__in=scope["instituciones"])
        candidates.extend(
            _candidate_dict("INSTITUTION", alias.institucion, "exact_alias", alias.alias_normalizado)
            for alias in alias_qs.select_related("institucion")
        )

        if _is_acronym(mention.surface):
            acronym = normalize_name(mention.surface)
            acronym_matches = [
                inst
                for inst in qs_inst.filter(nombre_normalizado__contains=acronym)
            ]
            candidates.extend(
                _candidate_dict("INSTITUTION", inst, "partial", acronym)
                for inst in acronym_matches
            )

    return _dedupe_candidates(candidates)[:limit]


def score_candidates(mention, candidates):
    scored = []
    context = normalize_name(mention.context_window)
    for candidate in candidates:
        match_type = candidate["match_type"]
        score = BASE_SCORES.get(match_type, 0.0)
        reasons = [
            {
                "rule": match_type,
                "value": candidate["matched_value"],
                "score_delta": BASE_SCORES.get(match_type, 0.0),
            }
        ]
        if context:
            score, reasons = _apply_context_boost(
                candidate,
                context,
                score,
                reasons,
            )
        scored.append({**candidate, "confidence": min(score, 1.0), "reasons": reasons})

    scored.sort(key=lambda item: item["confidence"], reverse=True)
    if len(scored) > 1 and (scored[0]["confidence"] - scored[1]["confidence"]) < 0.07:
        for item in scored[:2]:
            item["confidence"] = max(item["confidence"] - 0.15, 0.0)
            item["reasons"].append(
                {"rule": "ambiguity_penalty", "value": "close_scores", "score_delta": -0.15}
            )

    return scored


def choose_winner(scored_candidates, thresholds=None):
    if not scored_candidates:
        return None
    thresholds = thresholds or STATUS_THRESHOLDS
    winner = scored_candidates[0]
    confidence = winner["confidence"]
    if confidence >= thresholds["linked"]:
        status = EntityLink.Status.LINKED
    elif confidence >= thresholds["proposed"]:
        status = EntityLink.Status.PROPOSED
    else:
        return None
    return {**winner, "status": status}


def persist_link(mention, winner, resolver_version="linker_v1", dry_run=False):
    if not winner:
        return None, False
    status = winner["status"]
    entity_type = winner["entity_type"]
    entity_id = winner["entity_id"]
    defaults = {
        "entity_type": entity_type,
        "entity_id": entity_id,
        "status": status,
        "confidence": winner["confidence"],
        "reasons": winner["reasons"],
        "resolver_version": resolver_version,
    }
    if dry_run:
        return None, "noop"

    with transaction.atomic():
        existing_linked = EntityLink.objects.filter(
            mention=mention, status=EntityLink.Status.LINKED
        ).first()
        if status == EntityLink.Status.LINKED:
            if existing_linked:
                changed = (
                    existing_linked.entity_type != entity_type
                    or existing_linked.entity_id != entity_id
                )
                for field, value in defaults.items():
                    setattr(existing_linked, field, value)
                existing_linked.save()
                _sync_article_entity(mention.article, entity_type, entity_id, winner["confidence"])
                return existing_linked, "updated" if changed else "noop"

            proposed = EntityLink.objects.filter(
                mention=mention, status=EntityLink.Status.PROPOSED
            ).first()
            if proposed:
                for field, value in defaults.items():
                    setattr(proposed, field, value)
                proposed.save()
                _sync_article_entity(mention.article, entity_type, entity_id, winner["confidence"])
                return proposed, "updated"

            link = EntityLink.objects.create(mention=mention, **defaults)
            _sync_article_entity(mention.article, entity_type, entity_id, winner["confidence"])
            return link, "created"

        if existing_linked:
            return existing_linked, "noop"

        existing_proposed = EntityLink.objects.filter(
            mention=mention, status=EntityLink.Status.PROPOSED
        ).first()
        if existing_proposed:
            for field, value in defaults.items():
                setattr(existing_proposed, field, value)
            existing_proposed.save()
            return existing_proposed, "updated"
        link = EntityLink.objects.create(mention=mention, **defaults)
        return link, "created"


def ai_validate_match(client, model, threshold, mention, winner):
    entity = winner["entity"]
    entity_label = getattr(entity, "nombre_completo", None) or getattr(entity, "nombre", "") or ""
    context = (mention.context_window or "").strip() or (mention.article.lead or "").strip()
    if not context:
        return {"is_match": True, "confidence": 1.0, "reason": "context_missing"}
    payload = {
        "entity_label": entity_label,
        "entity_type": winner["entity_type"],
        "mention_surface": mention.surface,
        "context": context[:1200],
        "article_title": (mention.article.title or "")[:200],
    }
    prompt = (
        "Valida si la mención en el contexto se refiere a la entidad indicada. "
        "Responde SOLO JSON con llaves: is_match (true/false), confidence (0-1), reason."
        f"\n\nEntidad: {payload['entity_label']}"
        f"\nTipo: {payload['entity_type']}"
        f"\nMención detectada: {payload['mention_surface']}"
        f"\nTítulo: {payload['article_title']}"
        f"\nContexto: {payload['context']}"
    )
    try:
        response = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": "Eres un validador de menciones. Responde SOLO JSON."},
                {"role": "user", "content": prompt},
            ],
            temperature=0.2,
            response_format={"type": "json_object"},
        )
    except Exception as exc:
        LOGGER.warning("Error OpenAI (validación IA): %s", exc)
        return None

    content = response.choices[0].message.content
    try:
        result = json.loads(content)
    except json.JSONDecodeError:
        LOGGER.warning("JSON inválido en verificación IA.")
        return None
    if not isinstance(result, dict):
        return None
    is_match = result.get("is_match")
    confidence = result.get("confidence", 0.0)
    reason = result.get("reason", "")
    if is_match is False or confidence < threshold:
        return {"is_match": False, "confidence": confidence, "reason": reason}
    return {"is_match": True, "confidence": confidence, "reason": reason}


def link_mentions(
    mentions,
    scope=None,
    thresholds=None,
    ai_client=None,
    ai_model=None,
    ai_threshold=0.6,
    require_ai_validation=False,
    resolver_version="linker_v1",
    dry_run=False,
    extra_reason=None,
):
    totals = {
        "mentions_analyzed": 0,
        "links_created": 0,
        "links_updated": 0,
        "proposed": 0,
        "ambiguous": 0,
        "no_candidates": 0,
        "ai_rejected": 0,
    }
    ai_error = False
    for mention in mentions:
        totals["mentions_analyzed"] += 1
        candidates = retrieve_candidates(mention, scope=scope)
        if not candidates:
            totals["no_candidates"] += 1
            continue
        scored = score_candidates(mention, candidates)
        winner = choose_winner(scored, thresholds=thresholds)
        if not winner:
            totals["ambiguous"] += 1
            continue
        if extra_reason:
            winner["reasons"].append(extra_reason)
        if require_ai_validation:
            validation = ai_validate_match(
                ai_client,
                ai_model,
                ai_threshold,
                mention,
                winner,
            )
            if validation is None:
                ai_error = True
                continue
            if not validation.get("is_match"):
                totals["ai_rejected"] += 1
                continue
            winner["reasons"].append(
                {
                    "rule": "ai_validation",
                    "value": validation.get("reason", ""),
                    "confidence": validation.get("confidence", 0.0),
                    "score_delta": 0.0,
                }
            )
        link, action = persist_link(
            mention,
            winner,
            resolver_version=resolver_version,
            dry_run=dry_run,
        )
        if not link:
            continue
        if link.status == EntityLink.Status.PROPOSED:
            totals["proposed"] += 1
        elif action == "updated":
            totals["links_updated"] += 1
        elif action == "created":
            totals["links_created"] += 1
    return totals, ai_error



def _build_entries_for_aliases(alias_objects, entities):
    seen = set()
    entries = []
    for alias_obj in alias_objects:
        alias = (alias_obj.alias or "").strip()
        if not alias:
            continue
        key = alias.lower()
        if key in seen:
            continue
        entries.append(alias)
        seen.add(key)
    for entity in entities:
        name = (getattr(entity, "nombre_completo", None) or getattr(entity, "nombre", "") or "").strip()
        if not name:
            continue
        key = name.lower()
        if key in seen:
            continue
        entries.append(name)
        seen.add(key)
    return entries


def _build_alias_regex(entries):
    if not entries:
        return {}, None
    unique_aliases = sorted(set(entries), key=len, reverse=True)
    pattern = r"(?<!\\w)(" + "|".join(map(re.escape, unique_aliases)) + r")(?!\\w)"
    return {}, re.compile(pattern, re.IGNORECASE)


def _candidate_dict(entity_type, entity, match_type, matched_value):
    return {
        "entity_type": entity_type,
        "entity_id": entity.id,
        "entity": entity,
        "match_type": match_type,
        "matched_value": matched_value,
    }


def _dedupe_candidates(candidates):
    seen = {}
    for candidate in candidates:
        key = (candidate["entity_type"], candidate["entity_id"])
        existing = seen.get(key)
        if not existing:
            seen[key] = candidate
        else:
            if BASE_SCORES.get(candidate["match_type"], 0) > BASE_SCORES.get(existing["match_type"], 0):
                seen[key] = candidate
    return list(seen.values())


def _apply_context_boost(candidate, context, score, reasons):
    entity = candidate["entity"]
    boost = 0.0
    for keyword, rule in CONTEXT_KEYWORDS.items():
        if keyword not in context:
            continue
        if candidate["entity_type"] == "PERSON":
            if rule.get("cargo") and Cargo.objects.filter(
                persona=entity,
                nombre_cargo__icontains=rule["cargo"],
            ).exists():
                boost = 0.08
        else:
            if keyword in normalize_name(getattr(entity, "nombre", "")):
                boost = 0.05
        if boost:
            reasons.append(
                {"rule": "context_keyword", "value": keyword, "score_delta": boost}
            )
            score += boost
    return score, reasons


def _sync_article_entity(article, entity_type, entity_id, confidence):
    article_entity, _ = ArticleEntity.objects.get_or_create(
        article=article,
        entity_type=entity_type,
        entity_id=entity_id,
        defaults={"max_confidence": confidence},
    )
    if article_entity.max_confidence < confidence:
        article_entity.max_confidence = confidence
        article_entity.save(update_fields=["max_confidence"])


def _is_acronym(surface):
    if not surface:
        return False
    return surface.isupper() and len(surface) <= 6


def _should_skip_surface(surface: str) -> bool:
    cleaned = (surface or "").strip()
    if not cleaned:
        return True
    if len(cleaned) <= 2:
        return True
    normalized = normalize_name(cleaned)
    if not normalized or normalized.isdigit():
        return True
    if normalized in MENTION_STOP_WORDS:
        return True
    return False


def _find_surface_span(surface, text):
    if not surface or not text:
        return None, None
    pattern = re.escape(surface.strip())
    match = re.search(pattern, text, flags=re.IGNORECASE)
    if not match:
        return None, None
    return match.start(), match.end()
