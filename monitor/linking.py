import re
import logging
from django.db import transaction

from atlas_core.text_utils import normalize_name
from monitor.models import (
    Mention,
    EntityLink,
    ArticleEntity,
)
from redpolitica.models import Persona, Institucion

logger = logging.getLogger(__name__)

# --- CONSTANTS & STOPLISTS ---

# Words that should NOT be considered entities even if capitalized
MENTION_STOP_WORDS = {
    "EL", "LA", "LOS", "LAS", "UN", "UNA", "UNOS", "UNAS",
    "Y", "O", "DE", "DEL", "AL", "POR", "PARA", "CON", "SIN",
    "EN", "SOBRE", "TRAS", "ENTRE", "HACIA", "HASTA",
    "ESTE", "ESE", "AQUEL", "MI", "TU", "SU",
    "QUE", "CUAL", "QUIEN", "CUYO",
    "NO", "SI", "PERO", "SINO", "MAS", "AUNQUE",
    "HOY", "AYER", "MAÑANA", "AHORA", "ANTES", "DESPUES",
    "LUNES", "MARTES", "MIERCOLES", "JUEVES", "VIERNES", "SABADO", "DOMINGO",
    "ENERO", "FEBRERO", "MARZO", "ABRIL", "MAYO", "JUNIO",
    "JULIO", "AGOSTO", "SEPTIEMBRE", "OCTUBRE", "NOVIEMBRE", "DICIEMBRE",
    "MEXICO", "MÉXICO", "QUERETARO", "QUERÉTARO", "QRO",
    "GOBIERNO", "ESTADO", "MUNICIPIO", "PAIS", "NACION",
    "PRESIDENTE", "GOBERNADOR", "ALCALDE", "SECRETARIO", "DIPUTADO", "SENADOR",
    "DIRECTOR", "COORDINADOR", "JEFE", "TITULAR",
    "SECRETARIA", "DIRECCION", "COORDINACION", "JEFATURA",
    "NOTICIAS", "REPORTAJE", "REDACCION", "EDITORIAL", "FUENTE", "AUTOR",
}

# Thresholds for linking status
STATUS_THRESHOLDS = {
    "linked": 0.95,      # High confidence for automatic linking
    "proposed": 0.65,    # Limit for proposal
}


def link_mentions(
    article_pool,
    limit=1000,
    resolver_version="linker_v1",
    thresholds=None,
    ai_model=None,
    skip_ai_verify=True,
):
    """
    Main entry point for batch linking.
    Fallback strategy (no Alias models):
      - Build alias list from Persona.nombre_completo and Institucion.nombre
      - Regex match over article text
    """
    thresholds = thresholds or STATUS_THRESHOLDS
    processed_count = 0
    mentions_created = 0
    links_created = 0
    links_updated = 0

    alias_map, alias_regex = load_alias_map()
    if not alias_regex:
        logger.warning("No aliases (from Persona/Institucion) found. Skipping linking.")
        return {
            "processed": 0,
            "mentions_created": 0,
            "links_created": 0,
            "links_updated": 0,
        }

    for article in article_pool:
        text = ((article.title or "") + "\n" + (article.body_text or "")).strip()
        if not text:
            continue

        found_mentions = []

        for match in alias_regex.finditer(text):
            surface = match.group()
            if _should_skip_surface(surface):
                continue

            span = match.span()
            normalized = normalize_name(surface)

            mention, created = Mention.objects.get_or_create(
                article=article,
                normalized_surface=normalized,
                defaults={
                    "surface": surface,
                    "entity_kind": Mention.EntityKind.OTHER,
                    "span_start": span[0],
                    "span_end": span[1],
                    "context_window": text[max(0, span[0]-50):min(len(text), span[1]+50)]
                }
            )
            if created:
                mentions_created += 1
            found_mentions.append(mention)

        for mention in found_mentions:
            candidates = get_candidates(mention, alias_map)
            scored = score_candidates(mention, candidates)
            winner = choose_winner(scored, thresholds)

            if winner and winner["status"] == EntityLink.Status.PROPOSED and not skip_ai_verify:
                # Hook for optional AI verification later
                pass

            link, result = persist_link(mention, winner, resolver_version)
            if result == "created":
                links_created += 1
            elif result == "updated":
                links_updated += 1

        processed_count += 1
        if processed_count >= limit:
            break

    return {
        "processed": processed_count,
        "mentions_created": mentions_created,
        "links_created": links_created,
        "links_updated": links_updated,
    }


def load_alias_map():
    """
    Fallback alias loader when PersonaAlias/InstitucionAlias models do not exist.

    Returns:
      alias_map: { normalized_alias: [ {id, type, name, match_quality}, ... ] }
      alias_regex: compiled regex of all alias surfaces
    """
    alias_map = {}
    all_surfaces = set()

    # Personas: use nombre_completo as surface
    for p in Persona.objects.only("id", "nombre_completo").iterator():
        surface = (p.nombre_completo or "").strip()
        if not surface:
            continue
        norm = normalize_name(surface)
        if not norm:
            continue

        alias_map.setdefault(norm, []).append({
            "type": EntityLink.EntityType.PERSON,
            "id": p.id,
            "name": surface,
            "match_quality": 1.0,
        })
        all_surfaces.add(surface)

    # Instituciones: use nombre as surface
    for i in Institucion.objects.only("id", "nombre").iterator():
        surface = (i.nombre or "").strip()
        if not surface:
            continue
        norm = normalize_name(surface)
        if not norm:
            continue

        alias_map.setdefault(norm, []).append({
            "type": EntityLink.EntityType.INSTITUTION,
            "id": i.id,
            "name": surface,
            "match_quality": 1.0,
        })
        all_surfaces.add(surface)

    regex = _build_alias_regex(all_surfaces)
    return alias_map, regex


def _build_alias_regex(entries):
    if not entries:
        return None

    # Sort by length descending to match longest first
    unique_aliases = sorted([e for e in entries if e and len(e) > 2], key=len, reverse=True)
    if not unique_aliases:
        return None

    # Word-boundary-ish without splitting accents
    pattern = r"(?<!\w)(" + "|".join(map(re.escape, unique_aliases)) + r")(?!\w)"
    return re.compile(pattern, re.IGNORECASE)


def _should_skip_surface(surface: str) -> bool:
    cleaned = (surface or "").strip()
    if not cleaned:
        return True
    if len(cleaned) <= 2:
        return True

    normalized = normalize_name(cleaned)
    if not normalized or normalized.isdigit():
        return True

    if normalized.upper() in MENTION_STOP_WORDS:
        return True

    return False


def get_candidates(mention, alias_map):
    norm = mention.normalized_surface
    return alias_map.get(norm, [])


def score_candidates(mention, candidates):
    """
    Simple scoring:
    1) Exact surface match (via our alias map) = 1.0
    2) If multiple candidates share the same normalized surface -> ambiguity penalty
    """
    if not candidates:
        return []

    scored = []
    for cand in candidates:
        score = cand.get("match_quality", 1.0)
        scored.append({
            "entity_type": cand["type"],
            "entity_id": cand["id"],
            "confidence": float(score),
            "reasons": ["Name match (fallback)"],
        })

    if len(scored) > 1:
        for s in scored:
            s["confidence"] = s["confidence"] * 0.8
            s["reasons"].append("Ambiguous name")

    return sorted(scored, key=lambda x: x["confidence"], reverse=True)


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
        return None, "noop"

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
                if changed:
                    for field, value in defaults.items():
                        setattr(existing_linked, field, value)
                    existing_linked.save()
                    _sync_article_entity(mention.article, entity_type, entity_id, winner["confidence"])
                    return existing_linked, "updated"
                return existing_linked, "noop"

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

        # status == PROPOSED
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


def sync_article_mentions_from_links(articles, dry_run=False):
    if dry_run:
        return {
            "article_entities_synced": 0,
            "persona_mentions_created": 0,
            "institucion_mentions_created": 0,
        }

    linked_links = EntityLink.objects.filter(
        status=EntityLink.Status.LINKED,
        mention__article__in=articles,
    ).select_related("mention", "mention__article")

    totals = {
        "article_entities_synced": 0,
        "persona_mentions_created": 0,
        "institucion_mentions_created": 0,
    }
    for link in linked_links.iterator():
        result = _sync_article_entity(
            link.mention.article,
            link.entity_type,
            link.entity_id,
            link.confidence,
        )
        totals["article_entities_synced"] += int(result["article_entity_created"])
        totals["persona_mentions_created"] += int(result["persona_mentions_created"])
        totals["institucion_mentions_created"] += int(result["institucion_mentions_created"])

    return totals


def _sync_article_entity(article, entity_type, entity_id, confidence):
    article_entity, article_entity_created = ArticleEntity.objects.get_or_create(
        article=article,
        entity_type=entity_type,
        entity_id=entity_id,
        defaults={"max_confidence": confidence},
    )
    if article_entity.max_confidence < confidence:
        article_entity.max_confidence = confidence
        article_entity.save(update_fields=["max_confidence"])

    # Delay import to avoid circular dependency in some contexts
    from monitor.models import ArticlePersonaMention, ArticleInstitucionMention, EntityLink as _EntityLink

    persona_mentions_created = False
    institucion_mentions_created = False

    if entity_type == _EntityLink.EntityType.PERSON:
        _, persona_mentions_created = ArticlePersonaMention.objects.get_or_create(
            article=article,
            persona_id=entity_id,
            defaults={},
        )
    elif entity_type == _EntityLink.EntityType.INSTITUTION:
        _, institucion_mentions_created = ArticleInstitucionMention.objects.get_or_create(
            article=article,
            institucion_id=entity_id,
            defaults={},
        )

    return {
        "article_entity_created": article_entity_created,
        "persona_mentions_created": persona_mentions_created,
        "institucion_mentions_created": institucion_mentions_created,
    }
