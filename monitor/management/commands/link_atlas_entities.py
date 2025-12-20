import re
from django.core.management.base import BaseCommand
from django.utils import timezone

from monitor.models import (
    Article,
    PersonaAlias, InstitucionAlias,
    ArticlePersonaMention, ArticleInstitucionMention
)

class Command(BaseCommand):
    help = "Link Atlas personas/instituciones to Monitor articles via aliases."

    def add_arguments(self, parser):
        parser.add_argument("--hours", type=int, default=72)
        parser.add_argument("--limit", type=int, default=300)

    def handle(self, *args, **opts):
        hours = opts["hours"]
        limit = opts["limit"]
        since = timezone.now() - timezone.timedelta(hours=hours)

        articles = list(
            Article.objects.filter(published_at__gte=since)
            .order_by("-published_at", "-id")[:limit]
        )

        self.stdout.write(f"Articles to scan: {len(articles)} (last {hours}h)")

        persona_aliases = list(PersonaAlias.objects.select_related("persona").all())
        inst_aliases = list(InstitucionAlias.objects.select_related("institucion").all())

        created_p = 0
        created_i = 0

        for a in articles:
            text = " ".join([
                a.title or "",
                getattr(a, "lead", "") or "",
                getattr(a, "body_text", "") or "",
            ]).lower()

            # Personas
            for pa in persona_aliases:
                alias = (pa.alias or "").strip()
                if not alias:
                    continue
                pattern = r"(?<!\w)" + re.escape(alias.lower()) + r"(?!\w)"
                if re.search(pattern, text):
                    _, was_created = ArticlePersonaMention.objects.get_or_create(
                        article=a,
                        persona=pa.persona,
                        defaults={"matched_alias": alias},
                    )
                    if was_created:
                        created_p += 1

            # Instituciones
            for ia in inst_aliases:
                alias = (ia.alias or "").strip()
                if not alias:
                    continue
                pattern = r"(?<!\w)" + re.escape(alias.lower()) + r"(?!\w)"
                if re.search(pattern, text):
                    _, was_created = ArticleInstitucionMention.objects.get_or_create(
                        article=a,
                        institucion=ia.institucion,
                        defaults={"matched_alias": alias},
                    )
                    if was_created:
                        created_i += 1

        self.stdout.write(self.style.SUCCESS(
            f"Done. Created persona mentions: {created_p} · institution mentions: {created_i}"
        ))
