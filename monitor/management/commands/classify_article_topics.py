import json
import os

from django.core.management.base import BaseCommand

from openai import OpenAI

from monitor.models import Article


PROMPT_TEMPLATE = """
Clasifica los temas principales del artículo.
Devuelve SOLO un JSON válido con la llave: topics.

Cada item en topics debe incluir:
- label: tema breve (máximo 4 palabras)
- confidence: alta | media | baja

Devuelve entre 1 y 4 temas.

Título: {title}
Lead: {lead}
Cuerpo: {body}
""".strip()


class Command(BaseCommand):
    help = "Clasifica temas principales de artículos usando IA."

    def add_arguments(self, parser):
        parser.add_argument("--limit", type=int, default=40)
        parser.add_argument("--model", type=str, default="gpt-4o-mini")
        parser.add_argument("--force", action="store_true")

    def handle(self, *args, **opts):
        limit = opts["limit"]
        model = opts["model"]
        force = opts["force"]

        if not os.environ.get("OPENAI_API_KEY"):
            self.stdout.write(self.style.ERROR("OPENAI_API_KEY no está configurada en el entorno."))
            return

        client = OpenAI(api_key=os.environ.get("OPENAI_API_KEY"))

        qs = Article.objects.order_by("-id")
        if not force:
            qs = qs.filter(topics=[])
        articles = qs[:limit]
        self.stdout.write(f"Artículos a clasificar: {articles.count()}")

        allowed_confidence = {"alta", "media", "baja"}

        for article in articles:
            payload = self._build_prompt(article)
            result = self._classify(client, model, payload)
            if not result:
                self.stdout.write(self.style.WARNING(f"FAIL article {article.id}"))
                continue

            topics = result.get("topics")
            if not isinstance(topics, list) or not topics:
                self.stdout.write(self.style.WARNING(f"Topics inválidos article {article.id}: {topics}"))
                continue

            cleaned = []
            for topic in topics:
                if isinstance(topic, str):
                    label = topic.strip()
                    confidence = "media"
                elif isinstance(topic, dict):
                    label = str(topic.get("label", "")).strip()
                    confidence = str(topic.get("confidence", "media")).strip().lower()
                else:
                    continue

                if not label:
                    continue
                if confidence not in allowed_confidence:
                    confidence = "media"
                cleaned.append({"label": label, "confidence": confidence})

            if not cleaned:
                self.stdout.write(self.style.WARNING(f"Topics vacíos article {article.id}"))
                continue

            article.topics = cleaned
            article.topics_model = model
            article.topics_justification = result.get("justification", "")
            article.save(update_fields=["topics", "topics_model", "topics_justification"])
            self.stdout.write(self.style.SUCCESS(f"OK article {article.id}"))

    def _build_prompt(self, article):
        title = (article.title or "").strip()
        lead = (article.lead or "").strip()
        body = (article.body_text or "").strip()
        if body:
            body = body[:6000]
        return PROMPT_TEMPLATE.format(title=title, lead=lead, body=body)

    def _classify(self, client, model, payload):
        try:
            response = client.chat.completions.create(
                model=model,
                messages=[
                    {
                        "role": "system",
                        "content": "Eres un analista editorial. Responde SOLO JSON.",
                    },
                    {"role": "user", "content": payload},
                ],
                temperature=0.2,
                response_format={"type": "json_object"},
            )
        except Exception as exc:
            self.stdout.write(self.style.WARNING(f"Error OpenAI: {exc}"))
            return None

        content = response.choices[0].message.content
        try:
            return json.loads(content)
        except json.JSONDecodeError:
            self.stdout.write(self.style.WARNING("JSON inválido en respuesta de IA."))
            return None
