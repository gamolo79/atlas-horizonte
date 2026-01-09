import json
import logging
import os
import re
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Optional, Set

from openai import OpenAI
from rapidfuzz import fuzz

from atlas_core.text_utils import normalize_name, tokenize


NAME_FIELDS = ["nombre", "name", "title", "titulo", "label"]
ALIASES_FIELDS = ["aliases", "alias", "aka", "apodos"]
logger = logging.getLogger(__name__)
FUZZY_MATCH_THRESHOLD = 90
CATALOG_FALLBACK_SIZE = 25


def get_display_name(obj) -> str:
    for field in NAME_FIELDS:
        value = getattr(obj, field, None)
        if value:
            return str(value).strip()
    return str(obj).strip()


def get_aliases(obj) -> List[str]:
    for field in ALIASES_FIELDS:
        value = getattr(obj, field, None)
        if not value:
            continue
        if isinstance(value, str):
            return [item.strip() for item in value.split(",") if item.strip()]
        if isinstance(value, list):
            return [str(item).strip() for item in value if str(item).strip()]
    return []


@dataclass(frozen=True)
class CatalogEntry:
    target_type: str
    target_id: int
    target_name: str
    normalized_name: str


def build_catalog(personas, instituciones, temas) -> Dict[str, List[CatalogEntry]]:
    catalog: Dict[str, List[CatalogEntry]] = {"persona": [], "institucion": [], "tema": []}
    for persona in personas:
        display_name = get_display_name(persona)
        catalog["persona"].append(
            CatalogEntry(
                target_type="persona",
                target_id=persona.id,
                target_name=display_name,
                normalized_name=normalize_name(display_name),
            )
        )
        for alias in get_aliases(persona):
            catalog["persona"].append(
                CatalogEntry(
                    target_type="persona",
                    target_id=persona.id,
                    target_name=display_name,
                    normalized_name=normalize_name(alias),
                )
            )
    for institucion in instituciones:
        display_name = get_display_name(institucion)
        catalog["institucion"].append(
            CatalogEntry(
                target_type="institucion",
                target_id=institucion.id,
                target_name=display_name,
                normalized_name=normalize_name(display_name),
            )
        )
        for alias in get_aliases(institucion):
            catalog["institucion"].append(
                CatalogEntry(
                    target_type="institucion",
                    target_id=institucion.id,
                    target_name=display_name,
                    normalized_name=normalize_name(alias),
                )
            )
    for tema in temas:
        display_name = get_display_name(tema)
        catalog["tema"].append(
            CatalogEntry(
                target_type="tema",
                target_id=tema.id,
                target_name=display_name,
                normalized_name=normalize_name(display_name),
            )
        )
        for alias in get_aliases(tema):
            catalog["tema"].append(
                CatalogEntry(
                    target_type="tema",
                    target_id=tema.id,
                    target_name=display_name,
                    normalized_name=normalize_name(alias),
                )
            )
    return catalog


def catalog_prompt(catalog: Dict[str, List[CatalogEntry]], max_items: int = 200) -> str:
    lines = []
    for key, items in catalog.items():
        lines.append(f"{key.upper()}: ")
        for entry in items[:max_items]:
            lines.append(f"- {entry.target_name}")
        if len(items) > max_items:
            lines.append(f"- ... ({len(items) - max_items} más)")
    return "\n".join(lines)


def _entry_tokens(entry: CatalogEntry) -> Set[str]:
    return set(tokenize(entry.normalized_name))


def _article_text(article) -> str:
    return f"{getattr(article, 'title', '')} {getattr(article, 'text', '')}".strip()


def _article_tokens(text: str) -> Set[str]:
    return set(tokenize(text))


def filter_catalog_for_article(
    article,
    catalog: Dict[str, List[CatalogEntry]],
    fallback_size: int = CATALOG_FALLBACK_SIZE,
) -> Dict[str, List[CatalogEntry]]:
    text = _article_text(article)
    return filter_catalog_for_text(text, catalog, fallback_size=fallback_size)


def filter_catalog_for_text(
    text: str,
    catalog: Dict[str, List[CatalogEntry]],
    fallback_size: int = CATALOG_FALLBACK_SIZE,
) -> Dict[str, List[CatalogEntry]]:
    normalized_text = normalize_name(text)
    article_tokens = _article_tokens(text)
    if not normalized_text and not article_tokens:
        return catalog
    filtered: Dict[str, List[CatalogEntry]] = {}
    for key, entries in catalog.items():
        matches = [
            entry
            for entry in entries
            if entry.normalized_name in normalized_text or _entry_tokens(entry) & article_tokens
        ]
        if matches:
            filtered[key] = matches
        else:
            filtered[key] = entries[:fallback_size]
    return filtered


def parse_json_response(raw: str) -> Dict[str, Any]:
    cleaned = raw.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?", "", cleaned).strip()
        cleaned = re.sub(r"```$", "", cleaned).strip()
    return json.loads(cleaned)


def _normalize_mentions(raw_mentions: Any) -> List[Dict[str, Any]]:
    if raw_mentions is None:
        return []
    if isinstance(raw_mentions, list):
        return raw_mentions
    if isinstance(raw_mentions, dict):
        return [raw_mentions]
    if isinstance(raw_mentions, str):
        logger.warning("mentions llegó como string; se normaliza a lista vacía.")
        return []
    return []


def validate_payload(payload: Dict[str, Any]) -> Dict[str, Any]:
    required_keys = {"central_idea", "article_type", "labels"}
    if not required_keys.issubset(payload.keys()):
        raise ValueError("Faltan campos obligatorios en el JSON.")

    central_idea = payload["central_idea"]
    if not isinstance(central_idea, str):
        raise ValueError("central_idea debe ser string.")
    if len(central_idea.split()) > 30:
        raise ValueError("central_idea excede 30 palabras.")

    article_type = payload["article_type"]
    if article_type not in {"informativo", "opinion"}:
        raise ValueError("article_type inválido.")

    labels = payload["labels"]
    if not isinstance(labels, list) or len(labels) < 5 or not all(isinstance(label, str) for label in labels):
        raise ValueError("labels debe ser lista con al menos 5 elementos.")

    mentions = _normalize_mentions(payload.get("mentions"))
    payload["mentions"] = mentions
    for mention in mentions:
        if not isinstance(mention, dict):
            raise ValueError("mention inválida.")
        for key in ("target_type", "target_name", "sentiment", "confidence"):
            if key not in mention:
                raise ValueError("mention incompleta.")
        if mention["target_type"] not in {"persona", "institucion", "tema"}:
            raise ValueError("target_type inválido.")
        if mention["sentiment"] not in {"positivo", "neutro", "negativo"}:
            raise ValueError("sentiment inválido.")
        confidence = mention["confidence"]
        if not isinstance(confidence, (int, float)) or not 0 <= confidence <= 1:
            raise ValueError("confidence inválido.")
    return payload


def _fuzzy_score(source: str, candidate: str) -> int:
    return max(fuzz.ratio(source, candidate), fuzz.token_set_ratio(source, candidate))


def _find_fuzzy_match(
    normalized: str,
    entries: Iterable[CatalogEntry],
    threshold: int = FUZZY_MATCH_THRESHOLD,
) -> Optional[CatalogEntry]:
    best_entry: Optional[CatalogEntry] = None
    best_score = 0
    for entry in entries:
        score = _fuzzy_score(normalized, entry.normalized_name)
        if score > best_score:
            best_score = score
            best_entry = entry
    if best_entry and best_score >= threshold:
        return best_entry
    return None


def match_mentions(
    mentions: List[Dict[str, Any]],
    catalog: Dict[str, List[CatalogEntry]],
) -> List[Dict[str, Any]]:
    matches = []
    catalog_map: Dict[str, Dict[str, CatalogEntry]] = {
        key: {entry.normalized_name: entry for entry in entries}
        for key, entries in catalog.items()
    }
    for mention in mentions:
        normalized = normalize_name(mention["target_name"])
        entries = catalog.get(mention["target_type"], [])
        entry = catalog_map.get(mention["target_type"], {}).get(normalized)
        if not entry:
            entry = _find_fuzzy_match(normalized, entries)
        if not entry:
            continue
        matches.append(
            {
                "target_type": entry.target_type,
                "target_id": entry.target_id,
                "target_name": entry.target_name,
                "sentiment": mention["sentiment"],
                "confidence": float(mention["confidence"]),
            }
        )
    return matches


def classify_article(article, catalog: Dict[str, List[CatalogEntry]], retries: int = 2) -> Dict[str, Any]:
    model_name = os.environ.get("OPENAI_MODEL", "gpt-4o-mini")
    api_key = os.getenv("OPENAI_API_KEY")
    project_id = os.getenv("OPENAI_PROJECT_ID")
    if api_key and api_key.startswith("sk-proj-") and not project_id:
        raise RuntimeError("OPENAI_PROJECT_ID es requerido para claves sk-proj-*.")
    client = OpenAI(
        api_key=api_key,
        project=project_id,
    )
    filtered_catalog = filter_catalog_for_article(article, catalog)
    prompt = f"""
Eres un analista de cobertura mediática. Devuelve SOLO JSON estricto, sin texto extra.

Responde EXACTAMENTE con este schema:
{{
  "central_idea": "string (<=30 palabras)",
  "article_type": "informativo|opinion",
  "labels": ["etiqueta 1", "etiqueta 2", "etiqueta 3", "etiqueta 4", "etiqueta 5"],
  "mentions": [
    {{
      "target_type": "persona|institucion|tema",
      "target_name": "string",
      "sentiment": "positivo|neutro|negativo",
      "confidence": 0.0
    }}
  ]
}}

Reglas:
- mentions SIEMPRE debe ser un arreglo (puede estar vacío).
- labels debe ser un arreglo de strings (mínimo 5).
- central_idea debe ser string.
- article_type debe ser informativo u opinion.

Catálogo Atlas (para menciones):
{catalog_prompt(filtered_catalog)}

Artículo:
Título: {article.title}
Texto: {article.text[:6000]}
""".strip()

    last_error: Optional[Exception] = None
    for _ in range(retries + 1):
        try:
            response = client.chat.completions.create(
                model=model_name,
                messages=[
                    {"role": "system", "content": "Responde solo JSON válido."},
                    {"role": "user", "content": prompt},
                ],
                temperature=0.2,
            )
            raw = response.choices[0].message.content or ""
            payload = validate_payload(parse_json_response(raw))
            payload["_model_name"] = model_name
            return payload
        except Exception as exc:  # noqa: BLE001
            last_error = exc

    raise RuntimeError(f"Error al clasificar artículo: {last_error}")
