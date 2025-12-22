import os
import json
from django.core.management.base import BaseCommand
from django.utils import timezone
from monitor.models import Digest, DigestItem, StoryCluster

class Command(BaseCommand):
    help = "Generate AI summaries (synthesis) for Digest Items using LLM."

    def add_arguments(self, parser):
        parser.add_argument("--digest-date", type=str, help="YYYY-MM-DD", default=None)
        parser.add_argument("--force", action="store_true", help="Overwrite existing custom summaries")
        parser.add_argument("--model", type=str, default="gpt-4o-mini")

    def handle(self, *args, **opts):
        today = timezone.now().date()
        target_date_str = opts["digest_date"]
        
        if target_date_str:
            target_date = target_date_str
        else:
            target_date = today

        digest = Digest.objects.filter(date=target_date).order_by("-id").first()
        if not digest:
            self.stdout.write(self.style.ERROR(f"No digest found for date {target_date}"))
            return

        items = DigestItem.objects.filter(section__digest=digest).select_related("cluster")
        if not opts["force"]:
            # Skip items that already have a custom summary
            items = items.filter(custom_lead="")
        
        if not items.exists():
            self.stdout.write(self.style.SUCCESS("All items already have summaries."))
            return

        self.stdout.write(f"Generating summaries for {items.count()} items in digest {digest}...")
        
        api_key = os.environ.get("OPENAI_API_KEY")
        if not api_key:
            self.stdout.write(self.style.ERROR("OPENAI_API_KEY not found."))
            return
            
        try:
            from openai import OpenAI
            client = OpenAI(api_key=api_key)
        except ImportError:
            self.stdout.write(self.style.ERROR("openai package not installed."))
            return

        for item in items:
            cluster = item.cluster
            # Fetch context from mentions
            mentions = cluster.mentions.select_related("article").all()[:15] # Limit context
            
            context_texts = []
            for m in mentions:
                art = m.article
                txt = f"Título: {art.title}\nLead: {art.lead}"
                context_texts.append(txt)
            
            full_context = "\n---\n".join(context_texts)
            
            prompt = (
                "Eres un editor de noticias experto. Genera una síntesis ejecutiva breve de esta noticia.\n"
                "Output JSON: { \"headline\": \"Titular de impacto (max 10 palabras)\", \"summary\": \"Resumen en 3 bullets o parrafo corto (max 60 palabras).\" }\n"
                "Reglas: Sé neutral, directo y periodístico.\n\n"
                f"Noticias agrupadas:\n{full_context}"
            )

            try:
                response = client.chat.completions.create(
                    model=opts["model"],
                    messages=[
                        {"role": "system", "content": "Eres un asistente editorial. Respondes solo JSON."},
                        {"role": "user", "content": prompt}
                    ],
                    response_format={"type": "json_object"},
                    max_tokens=300
                )
                content = response.choices[0].message.content
                data = json.loads(content)
                
                item.custom_headline = data.get("headline", cluster.headline)
                item.custom_lead = data.get("summary", cluster.lead)
                item.save()
                
                self.stdout.write(f"Processed: {item.custom_headline}")
                
            except Exception as e:
                self.stdout.write(self.style.ERROR(f"Error processing item {item.id}: {e}"))

        self.stdout.write(self.style.SUCCESS("Synthesis generation complete."))
