import json
import os
import re
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from openai import OpenAI

from atlas_core.text_utils import normalize_name


@dataclass(frozen=True)
class CatalogEntry:
    target_type: str
    target_id: int
    target_name: str
    normalized_name: str


def build_catalog(personas, instituciones, temas) -> Dict[str, List[CatalogEntry]]:
    catalog: Dict[str, List[CatalogEntry]] = {"persona": [], "institucion": [], "tema": []}
    for persona in personas:
        catalog["persona"].append(
            CatalogEntry(
                target_type="persona",
                target_id=persona.id,
                target_name=persona.nombre_completo,
                normalized_name=normalize_name(persona.nombre_completo),
            )
        )
    for institucion in instituciones:
        catalog["institucion"].append(
            CatalogEntry(
                target_type="institucion",
                target_id=institucion.id,
                target_name=institucion.nombre,
                normalized_name=normalize_name(institucion.nombre),
            )
        )
    for tema in temas:
        catalog["tema"].append(
            CatalogEntry(
                target_type="tema",
                target_id=tema.id,
                target_name=tema.nombre,
                normalized_name=normalize_name(tema.nombre),
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


def parse_json_response(raw: str) -> Dict[str, Any]:
    cleaned = raw.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?", "", cleaned).strip()
        cleaned = re.sub(r"```$", "", cleaned).strip()
    return json.loads(cleaned)


def validate_payload(payload: Dict[str, Any]) -> Dict[str, Any]:
    required_keys = {"central_idea", "article_type", "labels", "mentions"}
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
    if not isinstance(labels, list) or len(labels) < 5:
        raise ValueError("labels debe ser lista con al menos 5 elementos.")

    mentions = payload["mentions"]
    if not isinstance(mentions, list):
        raise ValueError("mentions debe ser lista.")
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
        entry = catalog_map.get(mention["target_type"], {}).get(normalized)
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
    client = OpenAI()
    prompt = f"""
Eres un analista de cobertura mediática. Devuelve SOLO JSON estricto, sin texto extra.

Reglas:
- central_idea: máximo 30 palabras.
- labels: mínimo 5 etiquetas o frases cortas.
- article_type: informativo | opinion.
- sentimiento es hacia la Persona/Institución/tema mencionado.
- Puedes devolver mentions vacías si no hay match.

Catálogo Atlas (para menciones):
{catalog_prompt(catalog)}

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
