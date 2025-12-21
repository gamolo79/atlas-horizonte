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

        def build_alias_regex(alias_objs):
            alias_map = {}
            alias_values = []
            for alias_obj in alias_objs:
                alias = (alias_obj.alias or "").strip()
                if not alias:
                    continue
                alias_lower = alias.lower()
                alias_map.setdefault(alias_lower, []).append(alias_obj)
                alias_values.append(alias_lower)
            if not alias_values:
                return alias_map, None
            unique_aliases = sorted(set(alias_values), key=len, reverse=True)
            pattern = r"(?<!\w)(" + "|".join(map(re.escape, unique_aliases)) + r")(?!\w)"
            return alias_map, re.compile(pattern, re.IGNORECASE)

        persona_map, persona_regex = build_alias_regex(persona_aliases)
        inst_map, inst_regex = build_alias_regex(inst_aliases)

        created_p = 0
        created_i = 0

        for a in articles:
            text = " ".join([
                a.title or "",
                getattr(a, "lead", "") or "",
                getattr(a, "body_text", "") or "",
            ]).lower()

            # Personas
            if persona_regex:
                for match in persona_regex.finditer(text):
                    matched_alias = match.group(1).lower()
                    for pa in persona_map.get(matched_alias, []):
                        _, was_created = ArticlePersonaMention.objects.get_or_create(
                            article=a,
                            persona=pa.persona,
                            defaults={"matched_alias": pa.alias},
                        )
                        if was_created:
                            created_p += 1

            # Instituciones
            if inst_regex:
                for match in inst_regex.finditer(text):
                    matched_alias = match.group(1).lower()
                    for ia in inst_map.get(matched_alias, []):
                        _, was_created = ArticleInstitucionMention.objects.get_or_create(
                            article=a,
                            institucion=ia.institucion,
                            defaults={"matched_alias": ia.alias},
                        )
                        if was_created:
                            created_i += 1

        self.stdout.write(self.style.SUCCESS(
            f"Done. Created persona mentions: {created_p} · institution mentions: {created_i}"
        ))
