import os
from django.core.management.base import BaseCommand
from monitor.models import Article

from openai import OpenAI

client = OpenAI(api_key=os.environ.get("OPENAI_API_KEY"))


class Command(BaseCommand):
    help = "Create embeddings for articles using body_text."

    def add_arguments(self, parser):
        parser.add_argument("--limit", type=int, default=30)
        parser.add_argument("--force", action="store_true")
        parser.add_argument("--model", type=str, default="text-embedding-3-small")

    def handle(self, *args, **opts):
        limit = opts["limit"]
        force = opts["force"]
        model = opts["model"]

        qs = Article.objects.exclude(body_text="").order_by("-published_at", "-id")
        if not force:
            qs = qs.filter(embedding=[])

        qs = qs[:limit]
        self.stdout.write(f"Articles to embed: {qs.count()}")

        if not os.environ.get("OPENAI_API_KEY"):
            self.stdout.write(self.style.ERROR("OPENAI_API_KEY no está configurada en el entorno."))
            return

        for a in qs:
            try:
                text = (a.body_text or "")[:8000]
                if not text.strip():
                    self.stdout.write(self.style.WARNING(f"SKIP {a.id} empty body_text"))
                    continue

                emb = client.embeddings.create(model=model, input=text)
                vec = emb.data[0].embedding

                a.embedding = vec
                a.embedding_model = model
                a.save(update_fields=["embedding", "embedding_model"])

                self.stdout.write(self.style.SUCCESS(f"OK {a.id}"))
            except Exception as e:
                self.stdout.write(self.style.WARNING(f"FAIL {a.id} · {e}"))
