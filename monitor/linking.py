import re
import logging
from django.db import transaction
from django.db.models import Q
from atlas_core.text_utils import normalize_name
from monitor.models import Article, ActorLink, TopicLink
from redpolitica.models import Persona, Institucion, Topic

logger = logging.getLogger(__name__)

# --- CONSTANTS & STOPLISTS ---

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

def load_alias_map():
    """
    Builds a map of normalized names to entity IDs.
    Returns:
      alias_map: { normalized_name: [ {id, type, name, match_quality}, ... ] }
      alias_regex: compiled regex of all alias surfaces
    """
    alias_map = {}
    all_surfaces = set()

    # Personas
    for p in Persona.objects.only("id", "nombre_completo", "nombre_normalizado").iterator():
        surface = (p.nombre_completo or "").strip()
        if not _is_valid_surface(surface):
            continue
        
        norm = p.nombre_normalizado or normalize_name(surface)
        if not norm:
            continue

        alias_map.setdefault(norm, []).append({
            "type": ActorLink.AtlasEntityType.PERSONA,
            "id": str(p.id),
            "name": surface,
            "match_quality": 1.0,
        })
        all_surfaces.add(surface)

    # Instituciones
    for i in Institucion.objects.only("id", "nombre", "nombre_normalizado").iterator():
        surface = (i.nombre or "").strip()
        if not _is_valid_surface(surface):
            continue
            
        norm = i.nombre_normalizado or normalize_name(surface)
        if not norm:
            continue

        alias_map.setdefault(norm, []).append({
            "type": ActorLink.AtlasEntityType.INSTITUCION,
            "id": str(i.id),
            "name": surface,
            "match_quality": 1.0,
        })
        all_surfaces.add(surface)

    regex = _build_alias_regex(all_surfaces)
    return alias_map, regex


def load_topic_map():
    """
    Builds a map of normalized topic names to topic IDs.
    Returns:
      topic_map: { normalized_name: [ {id, name}, ... ] }
      topic_regex: compiled regex of all topic names
    """
    topic_map = {}
    all_surfaces = set()

    for topic in Topic.objects.only("id", "name").iterator():
        surface = (topic.name or "").strip()
        if not _is_valid_surface(surface):
            continue

        norm = normalize_name(surface)
        if not norm:
            continue

        topic_map.setdefault(norm, []).append({
            "id": str(topic.id),
            "name": surface,
        })
        all_surfaces.add(surface)

    regex = _build_alias_regex(all_surfaces)
    return topic_map, regex


def _is_valid_surface(surface: str) -> bool:
    cleaned = (surface or "").strip()
    if not cleaned or len(cleaned) <= 2:
        return False
    
    # Check stop words
    parts = cleaned.upper().split()
    if len(parts) == 1 and parts[0] in MENTION_STOP_WORDS:
        return False
        
    return True


def _build_alias_regex(entries):
    if not entries:
        return None

    # Sort by length descending to match longest first
    unique_aliases = sorted([e for e in entries if e and len(e) > 2], key=len, reverse=True)
    if not unique_aliases:
        return None

    # Escape and join
    pattern = r"(?<!\w)(" + "|".join(map(re.escape, unique_aliases)) + r")(?!\w)"
    try:
        return re.compile(pattern, re.IGNORECASE)
    except re.error:
        # Fallback if pattern is too large (rare but possible)
        logger.error("Alias regex too large to compile")
        return None


def link_content(
    article: Article,
    alias_map=None,
    alias_regex=None,
    topic_map=None,
    topic_regex=None,
) -> int:
    """
    Links entities in a single article.
    """
    if not alias_map or not alias_regex:
        alias_map, alias_regex = load_alias_map()
    if topic_map is None or topic_regex is None:
        topic_map, topic_regex = load_topic_map()

    text = ((article.title or "") + "\n" + (article.body or "")).strip()
    if not text:
        return 0

    found_links = 0
    # Keep track of what we've found to avoid duplicates per article
    found_entities = set()  # (type, id)
    found_topics = set()  # topic_id

    if alias_regex:
        for match in alias_regex.finditer(text):
            surface = match.group()
            norm = normalize_name(surface)
            candidates = alias_map.get(norm, [])

            if not candidates:
                continue

            # Simple strategy: if multiple candidates, pick the first one (can be improved)
            # OR if ambiguity is high, skip.
            # For now, let's take the first exact match candidate.
            winner = candidates[0]
            entity_key = (winner["type"], winner["id"])

            if entity_key in found_entities:
                continue

            # Create ActorLink
            try:
                ActorLink.objects.get_or_create(
                    article=article,
                    atlas_entity_type=winner["type"],
                    atlas_entity_id=winner["id"],
                    defaults={
                        "role_in_article": "mentioned",
                        "sentiment": ActorLink.Sentiment.NEUTRO,
                        "sentiment_confidence": 0.5,
                        "rationale": f"Regex match on '{surface}'",
                    },
                )
                found_entities.add(entity_key)
                found_links += 1
            except Exception as e:
                logger.error(f"Error linking {surface} to article {article.id}: {e}")

    if topic_regex:
        for match in topic_regex.finditer(text):
            surface = match.group()
            norm = normalize_name(surface)
            candidates = topic_map.get(norm, [])

            if not candidates:
                continue

            winner = candidates[0]
            topic_id = winner["id"]

            if topic_id in found_topics:
                continue

            try:
                TopicLink.objects.get_or_create(
                    article=article,
                    atlas_topic_id=topic_id,
                    defaults={
                        "confidence": 0.5,
                        "rationale": f"Regex match on '{surface}'",
                    },
                )
                found_topics.add(topic_id)
                found_links += 1
            except Exception as e:
                logger.error(f"Error linking topic {surface} to article {article.id}: {e}")

    return found_links


def run_linking(limit=1000):
    """
    Batch linking process.
    """
    # Find articles that haven't been linked yet? 
    # Or just re-link recent ones. For now, let's look for articles 
    # that don't have actor links or flag them?
    # Simplest: processed recent articles.
    
    # Optimization: Loading the map is expensive, do it once.
    alias_map, alias_regex = load_alias_map()
    topic_map, topic_regex = load_topic_map()
    if not alias_regex and not topic_regex:
        logger.warning("No aliases or topics found")
        return 0

    processed = 0
    # Process articles from last 24h or unlinked?
    # Let's target articles without ActorLinks or just recent ones.
    # For efficiency, let's just grab the last N articles.
    articles = Article.objects.all().order_by("-published_at")[:limit]

    for article in articles:
        # Optional: Skip if already has links?
        # if article.actor_links.exists(): continue
        
        count = link_content(article, alias_map, alias_regex, topic_map, topic_regex)
        processed += 1
        if count > 0:
            logger.info(f"Linked {count} entities in article {article.id}")

    return processed
