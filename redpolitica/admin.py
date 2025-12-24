from django.contrib import admin

from monitor.models import InstitucionAlias, PersonaAlias

from .models import (
    Persona,
    Institucion,
    Cargo,
    Relacion,
    PeriodoAdministrativo,
    Legislatura,
    Topic,
    InstitutionTopic,
    PersonTopicManual,
)


class PersonaAliasInline(admin.TabularInline):
    model = PersonaAlias
    extra = 1
    fields = ("alias",)


class InstitucionAliasInline(admin.TabularInline):
    model = InstitucionAlias
    extra = 1
    fields = ("alias",)


class InstitutionTopicInline(admin.TabularInline):
    model = InstitutionTopic
    extra = 1
    autocomplete_fields = ("institution", "topic")
    fields = ("institution", "topic", "role", "valid_from", "valid_to", "note")


class PersonTopicManualInline(admin.TabularInline):
    model = PersonTopicManual
    extra = 1
    autocomplete_fields = ("person", "topic")
    fields = ("person", "topic", "role", "source_url", "note")


@admin.register(Persona)
class PersonaAdmin(admin.ModelAdmin):
    list_display = ("nombre_completo", "fecha_nacimiento", "lugar_nacimiento")
    search_fields = ("nombre_completo", "slug", "lugar_nacimiento")
    prepopulated_fields = {"slug": ("nombre_completo",)}
    inlines = (PersonaAliasInline, PersonTopicManualInline)


@admin.register(Institucion)
class InstitucionAdmin(admin.ModelAdmin):
    list_display = (
        "nombre",
        "tipo",
        "ambito",
        "ciudad",
        "estado",
        "padre",
    )
    list_filter = ("tipo", "ambito", "estado", "padre")
    search_fields = ("nombre", "slug")
    prepopulated_fields = {"slug": ("nombre",)}
    autocomplete_fields = ("padre",)
    inlines = (InstitucionAliasInline, InstitutionTopicInline)


@admin.register(PeriodoAdministrativo)
class PeriodoAdministrativoAdmin(admin.ModelAdmin):
    list_display = ("nombre", "tipo", "nivel", "fecha_inicio", "fecha_fin", "institucion_raiz")
    list_filter = ("tipo", "nivel")
    search_fields = ("nombre",)
    autocomplete_fields = ("institucion_raiz",)


@admin.register(Legislatura)
class LegislaturaAdmin(admin.ModelAdmin):
    list_display = ("nombre", "numero", "periodo")
    list_filter = ("periodo",)
    search_fields = ("nombre",)
    autocomplete_fields = ("periodo",)


@admin.register(Cargo)
class CargoAdmin(admin.ModelAdmin):
    list_display = (
        "persona",
        "nombre_cargo",
        "institucion",
        "periodo",
        "fecha_inicio",
        "fecha_fin",
        "es_actual",
    )
    list_filter = ("es_actual", "periodo", "institucion__tipo", "institucion__ambito")
    search_fields = (
        "persona__nombre_completo",
        "nombre_cargo",
        "institucion__nombre",
    )
    autocomplete_fields = ("persona", "institucion", "periodo")


@admin.register(Relacion)
class RelacionAdmin(admin.ModelAdmin):
    list_display = ("origen", "destino", "tipo", "descripcion_corta", "fuente")
    list_filter = ("tipo",)
    search_fields = (
        "origen__nombre_completo",
        "destino__nombre_completo",
        "descripcion",
        "fuente",
    )
    autocomplete_fields = ("origen", "destino")

    def descripcion_corta(self, obj):
        if not obj.descripcion:
            return ""
        return (obj.descripcion[:60] + "…") if len(obj.descripcion) > 60 else obj.descripcion

    descripcion_corta.short_description = "Descripción"


@admin.register(Topic)
class TopicAdmin(admin.ModelAdmin):
    list_display = ("name", "topic_kind", "status", "parent", "updated_at")
    search_fields = ("name", "description")
    list_filter = ("topic_kind", "status")
    prepopulated_fields = {"slug": ("name",)}
    autocomplete_fields = ("parent",)
    inlines = (InstitutionTopicInline, PersonTopicManualInline)


@admin.register(InstitutionTopic)
class InstitutionTopicAdmin(admin.ModelAdmin):
    list_display = ("institution", "topic", "role", "valid_from", "valid_to")
    search_fields = ("institution__nombre", "topic__name", "role")
    autocomplete_fields = ("institution", "topic")


@admin.register(PersonTopicManual)
class PersonTopicManualAdmin(admin.ModelAdmin):
    list_display = ("person", "topic", "role", "source_url")
    search_fields = ("person__nombre_completo", "topic__name", "role")
    autocomplete_fields = ("person", "topic")
