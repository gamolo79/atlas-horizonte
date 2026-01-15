from __future__ import annotations

import hashlib
import os
from datetime import date
from typing import Iterable

from django.conf import settings
from django.db.models import Count

from monitor.services import parse_json_response
from sintesis.models import SynthesisCluster, SynthesisClusterLabelCache


def _story_key(cluster: SynthesisCluster, label_date: date) -> str:
    base = "|".join(
        [
            str(cluster.template_id or ""),
            ",".join(sorted(cluster.top_entities_json or [])),
            ",".join(sorted(cluster.top_tags_json or [])),
            label_date.isoformat(),
        ]
    )
    return hashlib.sha256(base.encode("utf-8")).hexdigest()[:24]


def _cluster_prompt_text(cluster: SynthesisCluster) -> str:
    members = cluster.members.select_related("article", "article__classification").order_by(
        "-article__published_at"
    )[:5]
    lines = []
    for member in members:
        article = member.article
        classification = getattr(article, "classification", None)
        central_idea = getattr(classification, "central_idea", "")
        labels = ", ".join(getattr(classification, "labels_json", []) or [])[:120]
        lines.append(
            f"- {article.title} | {central_idea} | {labels}"
        )
    return "\n".join(lines)


def _fallback_payload(cluster: SynthesisCluster) -> dict:
    title = ""
    if cluster.top_entities_json:
        title = f"Historia sobre {cluster.top_entities_json[0]}"
    elif cluster.top_tags_json:
        title = f"Historia sobre {cluster.top_tags_json[0]}"
    else:
        title = "Historia relevante"
    return {
        "story_title": title,
        "story_summary": "Resumen pendiente de procesamiento automático.",
        "key_entities": cluster.top_entities_json or [],
    }


def label_clusters(run_id: int, template_id: int) -> list[SynthesisCluster]:
    clusters = (
        SynthesisCluster.objects.filter(run_id=run_id, template_id=template_id)
        .annotate(member_count=Count("members"))
        .order_by("-member_count", "-created_at")
    )
    limit = getattr(settings, "SINTESIS_CLUSTER_LABEL_LIMIT", 8)
    api_key = os.getenv("OPENAI_API_KEY")
    project_id = os.getenv("OPENAI_PROJECT_ID")
    model_name = os.environ.get("OPENAI_MODEL", "gpt-4o-mini")
    updated = []

    for cluster in clusters[:limit]:
        label_date = (cluster.time_end.date() if cluster.time_end else date.today())
        story_key = _story_key(cluster, label_date)
        cached = SynthesisClusterLabelCache.objects.filter(
            story_key=story_key,
            label_date=label_date,
        ).first()
        if cached:
            payload = cached.payload_json or {}
        else:
            if not api_key:
                payload = _fallback_payload(cluster)
            else:
                if api_key.startswith("sk-proj-") and not project_id:
                    raise RuntimeError("OPENAI_PROJECT_ID es requerido para claves sk-proj-*.")
                from openai import OpenAI

                client = OpenAI(api_key=api_key, project=project_id)
                prompt = f"""
Eres un editor experto de noticias. Resume un cluster en una historia corta.

Instrucciones:
1. Crea un story_title (8-14 palabras).
2. Crea un story_summary (30-50 palabras).
3. Devuelve key_entities como lista.
4. Responde SOLO JSON válido.

Insumos:
{_cluster_prompt_text(cluster)}

Schema:
{{
  "story_title": "string",
  "story_summary": "string",
  "key_entities": ["string"]
}}
""".strip()
                response = client.chat.completions.create(
                    model=model_name,
                    messages=[
                        {"role": "system", "content": "Responde solo JSON válido."},
                        {"role": "user", "content": prompt},
                    ],
                    temperature=0.2,
                )
                raw = response.choices[0].message.content or ""
                payload = parse_json_response(raw) or _fallback_payload(cluster)

            SynthesisClusterLabelCache.objects.create(
                story_key=story_key,
                label_date=label_date,
                payload_json=payload,
            )

        cluster.story_key = story_key
        cluster.story_title = payload.get("story_title", "")
        cluster.story_summary = payload.get("story_summary", "")
        cluster.key_entities_json = payload.get("key_entities", [])
        cluster.save(
            update_fields=["story_key", "story_title", "story_summary", "key_entities_json"]
        )
        updated.append(cluster)

    return updated
