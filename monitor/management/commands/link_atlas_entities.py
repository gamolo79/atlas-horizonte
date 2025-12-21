import re
from django.core.management.base import BaseCommand
from django.db import connection
from django.utils import timezone

from monitor.models import (
    Article,
    PersonaAlias,
    InstitucionAlias,
    ArticlePersonaMention,
    ArticleInstitucionMention,
)
from redpolitica.models import Persona, Institucion

class Command(BaseCommand):
    help = "Link Atlas personas/instituciones to Monitor articles via aliases."

    def add_arguments(self, parser):
        parser.add_argument("--hours", type=int, default=72)
        parser.add_argument("--limit", type=int, default=300)

    def handle(self, *args, **opts):
        if not self._mentions_table_ready():
            self.stdout.write(
                self.style.WARNING(
                    "Las columnas de sentimiento por mención no están disponibles. "
                    "Ejecuta las migraciones antes de correr este comando."
                )
            )
            return

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

        def build_alias_regex(alias_entries):
            alias_map = {}
            alias_values = []
            for alias, entity in alias_entries:
                alias = (alias or "").strip()
                if not alias:
                    continue
                alias_lower = alias.lower()
                alias_map.setdefault(alias_lower, []).append((entity, alias))
                alias_values.append(alias_lower)
            if not alias_values:
                return alias_map, None
            unique_aliases = sorted(set(alias_values), key=len, reverse=True)
            pattern = r"(?<!\w)(" + "|".join(map(re.escape, unique_aliases)) + r")(?!\w)"
            return alias_map, re.compile(pattern, re.IGNORECASE)

        persona_entries = []
        seen_persona_aliases = set()
        for alias_obj in persona_aliases:
            key = ((alias_obj.alias or "").strip().lower(), alias_obj.persona_id)
            if not key[0] or key in seen_persona_aliases:
                continue
            seen_persona_aliases.add(key)
            persona_entries.append((alias_obj.alias, alias_obj.persona))
        for persona in Persona.objects.only("id", "nombre_completo"):
            key = ((persona.nombre_completo or "").strip().lower(), persona.id)
            if not key[0] or key in seen_persona_aliases:
                continue
            seen_persona_aliases.add(key)
            persona_entries.append((persona.nombre_completo, persona))

        institucion_entries = []
        seen_inst_aliases = set()
        for alias_obj in inst_aliases:
            key = ((alias_obj.alias or "").strip().lower(), alias_obj.institucion_id)
            if not key[0] or key in seen_inst_aliases:
                continue
            seen_inst_aliases.add(key)
            institucion_entries.append((alias_obj.alias, alias_obj.institucion))
        for institucion in Institucion.objects.only("id", "nombre"):
            key = ((institucion.nombre or "").strip().lower(), institucion.id)
            if not key[0] or key in seen_inst_aliases:
                continue
            seen_inst_aliases.add(key)
            institucion_entries.append((institucion.nombre, institucion))

        persona_map, persona_regex = build_alias_regex(persona_entries)
        inst_map, inst_regex = build_alias_regex(institucion_entries)

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
                    for persona, alias in persona_map.get(matched_alias, []):
                        _, was_created = ArticlePersonaMention.objects.get_or_create(
                            article=a,
                            persona=persona,
                            defaults={"matched_alias": alias},
                        )
                        if was_created:
                            created_p += 1

            # Instituciones
            if inst_regex:
                for match in inst_regex.finditer(text):
                    matched_alias = match.group(1).lower()
                    for institucion, alias in inst_map.get(matched_alias, []):
                        _, was_created = ArticleInstitucionMention.objects.get_or_create(
                            article=a,
                            institucion=institucion,
                            defaults={"matched_alias": alias},
                        )
                        if was_created:
                            created_i += 1

        self.stdout.write(self.style.SUCCESS(
            f"Done. Created persona mentions: {created_p} · institution mentions: {created_i}"
        ))

    def _mentions_table_ready(self):
        persona_table = ArticlePersonaMention._meta.db_table
        institucion_table = ArticleInstitucionMention._meta.db_table
        return (
            self._column_exists(persona_table, "sentiment")
            and self._column_exists(institucion_table, "sentiment")
        )

    def _column_exists(self, table_name, column_name):
        with connection.cursor() as cursor:
            columns = connection.introspection.get_table_description(cursor, table_name)
        return column_name in {column.name for column in columns}
