import json
import os

from django.core.management.base import BaseCommand

from openai import OpenAI

from monitor.models import ArticleInstitucionMention, ArticlePersonaMention, ArticleSentiment


PROMPT_TEMPLATE = """
Analiza el tono de la nota hacia la entidad indicada.
Devuelve SOLO un JSON válido con las llaves: sentiment, confidence, justification.

Valores permitidos:
- sentiment: positivo | neutro | negativo
- confidence: alta | media | baja

Entidad: {entity_label}
Tipo: {entity_type}

Título: {title}
Lead: {lead}
Cuerpo: {body}
""".strip()


class Command(BaseCommand):
    help = "Clasifica sentimiento por entidad (persona o institución) usando IA."

    def add_arguments(self, parser):
        parser.add_argument("--limit", type=int, default=40)
        parser.add_argument("--model", type=str, default="gpt-4o-mini")
        parser.add_argument(
            "--kind",
            type=str,
            choices=["persona", "institucion", "both"],
            default="both",
        )
        parser.add_argument("--force", action="store_true")

    def handle(self, *args, **opts):
        limit = opts["limit"]
        model = opts["model"]
        kind = opts["kind"]
        force = opts["force"]

        if not os.environ.get("OPENAI_API_KEY"):
            self.stdout.write(self.style.ERROR("OPENAI_API_KEY no está configurada en el entorno."))
            return

        client = OpenAI(api_key=os.environ.get("OPENAI_API_KEY"))

        if kind in ("persona", "both"):
            self._classify_persona_mentions(client, model, limit, force)

        if kind in ("institucion", "both"):
            self._classify_institution_mentions(client, model, limit, force)

    def _classify_persona_mentions(self, client, model, limit, force):
        qs = ArticlePersonaMention.objects.select_related("article", "persona").order_by("-id")
        if not force:
            qs = qs.filter(sentiment__isnull=True)
        mentions = qs[:limit]
        self.stdout.write(f"Personas a clasificar: {mentions.count()}")
        allowed_sentiments = {choice.value for choice in ArticleSentiment.Sentiment}

        for mention in mentions:
            article = mention.article
            entity_label = mention.persona.nombre_completo
            payload = self._build_prompt(entity_label, "persona", article)
            result = self._classify(client, model, payload)
            if not result:
                self.stdout.write(self.style.WARNING(f"FAIL persona {mention.id}"))
                continue

            sentiment = result.get("sentiment")
            if sentiment not in allowed_sentiments:
                self.stdout.write(self.style.WARNING(f"Sentiment inválido persona {mention.id}: {sentiment}"))
                continue

            mention.sentiment = sentiment
            mention.sentiment_confidence = result.get("confidence")
            mention.sentiment_justification = result.get("justification", "")
            mention.sentiment_model = model
            mention.save(
                update_fields=[
                    "sentiment",
                    "sentiment_confidence",
                    "sentiment_justification",
                    "sentiment_model",
                ]
            )
            self.stdout.write(self.style.SUCCESS(f"OK persona {mention.id}"))

    def _classify_institution_mentions(self, client, model, limit, force):
        qs = ArticleInstitucionMention.objects.select_related("article", "institucion").order_by("-id")
        if not force:
            qs = qs.filter(sentiment__isnull=True)
        mentions = qs[:limit]
        self.stdout.write(f"Instituciones a clasificar: {mentions.count()}")
        allowed_sentiments = {choice.value for choice in ArticleSentiment.Sentiment}

        for mention in mentions:
            article = mention.article
            entity_label = mention.institucion.nombre
            payload = self._build_prompt(entity_label, "institucion", article)
            result = self._classify(client, model, payload)
            if not result:
                self.stdout.write(self.style.WARNING(f"FAIL institucion {mention.id}"))
                continue

            sentiment = result.get("sentiment")
            if sentiment not in allowed_sentiments:
                self.stdout.write(self.style.WARNING(f"Sentiment inválido institucion {mention.id}: {sentiment}"))
                continue

            mention.sentiment = sentiment
            mention.sentiment_confidence = result.get("confidence")
            mention.sentiment_justification = result.get("justification", "")
            mention.sentiment_model = model
            mention.save(
                update_fields=[
                    "sentiment",
                    "sentiment_confidence",
                    "sentiment_justification",
                    "sentiment_model",
                ]
            )
            self.stdout.write(self.style.SUCCESS(f"OK institucion {mention.id}"))

    def _build_prompt(self, entity_label, entity_type, article):
        title = (article.title or "").strip()
        lead = (article.lead or "").strip()
        body = (article.body_text or "").strip()
        if body:
            body = body[:6000]
        return PROMPT_TEMPLATE.format(
            entity_label=entity_label,
            entity_type=entity_type,
            title=title,
            lead=lead,
            body=body,
        )

    def _classify(self, client, model, payload):
        from monitor.models import MonitorGoldLabel

        messages = [
            {
                "role": "system",
                "content": "Eres un analista de sentimiento editorial. Responde SOLO JSON.",
            }
        ]

        # Inject Few-Shot Examples (Sentiment)
        try:
            examples = MonitorGoldLabel.objects.filter(
                label_type=MonitorGoldLabel.LabelType.SENTIMENT
            ).order_by("-created_at")[:3]
            
            for ex in reversed(list(examples)):
                messages.append({"role": "user", "content": ex.reference_text})
                out_str = json.dumps(ex.output_json, ensure_ascii=False)
                messages.append({"role": "assistant", "content": out_str})
        except Exception:
            pass

        messages.append({"role": "user", "content": payload})

        try:
            response = client.chat.completions.create(
                model=model,
                messages=messages,
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
