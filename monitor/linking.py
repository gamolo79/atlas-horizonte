import re
import math
import logging
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from atlas_core.text_utils import normalize_name
from monitor.models import (
    Article,
    Mention,
    EntityLink,
    ArticleEntity,
    PersonaAlias,
    InstitucionAlias,
    ArticlePersonaMention,
    ArticleInstitucionMention,
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

# --- PUBLIC API ---

def link_mentions(article_pool, limit=1000, resolver_version="linker_v1", thresholds=None, ai_model=None, skip_ai_verify=True):
    """
    Main entry point for batch linking.
    """
    thresholds = thresholds or STATUS_THRESHOLDS
    processed_count = 0
    mentions_created = 0
    links_created = 0
    links_updated = 0
    
    # 1. Load Aliases into Memory (Optimization)
    alias_map, alias_regex = load_alias_map()
    if not alias_regex:
        logger.warning("No aliases found. Skipping linking.")
        return {
            "processed": 0,
            "mentions_created": 0,
            "links_created": 0,
            "links_updated": 0,
        }

    # 2. Iterate Articles
    for article in article_pool:
        # A. Extract Mentions (Regex based on Aliases)
        text = (article.title + "\n" + article.body_text).strip()
        if not text:
            continue
            
        found_matches = []
        # Find unique matches to avoid spamming DB with same mention 50 times per article
        # But we want positions? For now, let's just capture unique surfaces per article
        # or first occurrence.
        
        # Regex finditer
        for match in alias_regex.finditer(text):
            surface = match.group()
            if _should_skip_surface(surface):
                continue
            
            span = match.span()
            normalized = normalize_name(surface)
            
            # Create Mention object
            mention, created = Mention.objects.get_or_create(
                article=article,
                normalized_surface=normalized,
                defaults={
                    "surface": surface,
                    "entity_kind": Mention.EntityKind.OTHER, # We refine later based on Alias map
                    "span_start": span[0],
                    "span_end": span[1],
                    "context_window": text[max(0, span[0]-50):min(len(text), span[1]+50)]
                }
            )
            if created:
                mentions_created += 1
            found_matches.append(mention)
            
        # B. Resolve Candidates
        for mention in found_matches:
            candidates = get_candidates(mention, alias_map)
            scored = score_candidates(mention, candidates)
            winner = choose_winner(scored, thresholds)
            
            # C. AI Verification (Optional)
            if winner and winner["status"] == EntityLink.Status.PROPOSED and not skip_ai_verify:
                # Call AI to verify if ambiguous
                # verified_winner = verify_with_ai(...)
                # For now, skip to save tokens/latency unless requested
                pass

            # D. Persist Link
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

# --- INTERNAL HELPERS ---

def load_alias_map():
    """
    Returns:
      alias_map: { normalized_alias: [ {id, type, name, score_boost}, ... ] }
      alias_regex: compiled regex of all aliases
    """
    alias_map = {}
    all_surfaces = set()
    
    # Load Personas
    # Optimization: Use iterator
    for pa in PersonaAlias.objects.select_related("persona").iterator():
        norm = pa.alias_normalizado
        if not norm: continue
        if norm not in alias_map: alias_map[norm] = []
        alias_map[norm].append({
            "type": EntityLink.EntityType.PERSON,
            "id": pa.persona.id,
            "name": pa.persona.nombre_completo,
            "match_quality": 1.0 # Exact alias match
        })
        all_surfaces.add(pa.alias)
        
    # Load Institutions
    for ia in InstitucionAlias.objects.select_related("institucion").iterator():
        norm = ia.alias_normalizado
        if not norm: continue
        if norm not in alias_map: alias_map[norm] = []
        alias_map[norm].append({
            "type": EntityLink.EntityType.INSTITUTION,
            "id": ia.institucion.id,
            "name": ia.institucion.nombre,
            "match_quality": 1.0
        })
        all_surfaces.add(ia.alias)
        
    regex = _build_alias_regex(all_surfaces)
    return alias_map, regex

def _build_alias_regex(entries):
    if not entries:
        return None
    # Sort by length descending to match longest first ("Secretaría de Salud" before "Secretaría")
    unique_aliases = sorted([e for e in entries if e and len(e)>2], key=len, reverse=True)
    if not unique_aliases:
        return None
        
    # Batching for massive regex? 
    # Python's re engine handles large alternations okay-ish, but 10k+ might be slow.
    # For now assuming < 5000 aliases.
    
    pattern = r"(?<!\w)(" + "|".join(map(re.escape, unique_aliases)) + r")(?!\w)"
    return re.compile(pattern, re.IGNORECASE)

def _should_skip_surface(surface: str) -> bool:
    cleaned = (surface or "").strip()
    if not cleaned: return True
    if len(cleaned) <= 2: return True
    normalized = normalize_name(cleaned)
    if not normalized or normalized.isdigit(): return True
    
    # Check stop list
    if normalized.upper() in MENTION_STOP_WORDS:
        return True
        
    return False

def get_candidates(mention, alias_map):
    norm = mention.normalized_surface
    return alias_map.get(norm, [])

def score_candidates(mention, candidates):
    """
    Simple scoring: 
    1. Exact alias match = 1.0 (already set in loading)
    2. Disambiguation needed if multiple candidates.
    """
    if not candidates:
        return []
        
    scored = []
    for cand in candidates:
        # Logic to downgrade vague aliases?
        # e.g. "PAN" -> Partido Accion Nacional (High) vs "PAN" -> Panadería (Low - unmapped)
        # Here we only mapped explicit database aliases.
        
        # Ambiguity check: if multiple candidates have 1.0, we mark confidence lower?
        score = cand["match_quality"]
        
        scored.append({
            "entity_type": cand["type"],
            "entity_id": cand["id"],
            "confidence": score, # Placeholder for more complex logic
            "reasons": ["Alias match"]
        })
        
    # If multiple candidates, divide confidence?
    if len(scored) > 1:
        for s in scored:
            s["confidence"] = s["confidence"] * 0.8 # Penalty for ambiguity
            s["reasons"].append("Ambiguous alias")
            
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
        # Below threshold? Maybe REJECTED or just None
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
        "resolver_version": resolver_version
    }
    
    if dry_run:
        return None, "noop"

    with transaction.atomic():
        # Check existing linked (Official)
        existing_linked = EntityLink.objects.filter(mention=mention, status=EntityLink.Status.LINKED).first()
        
        if status == EntityLink.Status.LINKED:
            if existing_linked:
                # Update if different?
                changed = (existing_linked.entity_type != entity_type or existing_linked.entity_id != entity_id)
                if changed:
                    # Overwrite?
                    for field, value in defaults.items():
                        setattr(existing_linked, field, value)
                    existing_linked.save()
                    _sync_article_entity(mention.article, entity_type, entity_id, winner["confidence"])
                    return existing_linked, "updated"
                return existing_linked, "noop"
            
            # Check if there was a proposed one to promote
            proposed = EntityLink.objects.filter(mention=mention, status=EntityLink.Status.PROPOSED).first()
            if proposed:
                for field, value in defaults.items():
                    setattr(proposed, field, value)
                proposed.save()
                _sync_article_entity(mention.article, entity_type, entity_id, winner["confidence"])
                return proposed, "updated"
                
            # Create new Linked
            link = EntityLink.objects.create(mention=mention, **defaults)
            _sync_article_entity(mention.article, entity_type, entity_id, winner["confidence"])
            return link, "created"

        # If status == PROPOSED
        if existing_linked:
            # Don't downgrade a Linked to Proposed automatically
            return existing_linked, "noop"
            
        existing_proposed = EntityLink.objects.filter(mention=mention, status=EntityLink.Status.PROPOSED).first()
        if existing_proposed:
            # Update meta
            for field, value in defaults.items():
                setattr(existing_proposed, field, value)
            existing_proposed.save()
            return existing_proposed, "updated"
            
        link = EntityLink.objects.create(mention=mention, **defaults)
        return link, "created"

def _sync_article_entity(article, entity_type, entity_id, confidence):
    # 1. Base sync to ArticleEntity
    article_entity, _ = ArticleEntity.objects.get_or_create(
        article=article,
        entity_type=entity_type,
        entity_id=entity_id,
        defaults={"max_confidence": confidence},
    )
    if article_entity.max_confidence < confidence:
        article_entity.max_confidence = confidence
        article_entity.save(update_fields=["max_confidence"])

    # 2. Sync to Dashboard Tables (ArticlePersonaMention / ArticleInstitucionMention)
    # These tables are denormalized for fast dashboard querying (e.g. sentiment tracking)
    # We delay import to avoid circular dependency in some contexts
    from monitor.models import ArticlePersonaMention, ArticleInstitucionMention, EntityLink
    
    if entity_type == EntityLink.EntityType.PERSON:
        # Ensure Persona Mention exists
        ArticlePersonaMention.objects.get_or_create(
            article=article,
            persona_id=entity_id,
            defaults={} # Sentiment is updated elsewhere
        )
    elif entity_type == EntityLink.EntityType.INSTITUTION:
        ArticleInstitucionMention.objects.get_or_create(
            article=article,
            institucion_id=entity_id,
            defaults={}
        )
