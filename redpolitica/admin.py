from django.contrib import admin

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

@admin.register(Topic)
class TopicAdmin(admin.ModelAdmin):
    search_fields = ("name", "slug")
    list_display = ("name", "slug")
    prepopulated_fields = {"slug": ("name",)}

@admin.register(Persona)
class PersonaAdmin(admin.ModelAdmin):
    list_display = ("nombre_completo", "fecha_nacimiento", "lugar_nacimiento")
    search_fields = ("nombre_completo", "slug", "lugar_nacimiento")
    prepopulated_fields = {"slug": ("nombre_completo",)}
    inlines = (PersonTopicManualInline,)


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
    inlines = (InstitutionTopicInline,)


@admin.register(PeriodoAdministrativo)
class PeriodoAdministrativoAdmin(admin.ModelAdmin):
    list_display = ("nombre", "tipo", "nivel", "fecha_inicio", "fecha_fin")
    list_filter = ("tipo", "nivel")
    search_fields = ("nombre",)


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
