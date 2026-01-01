from django.contrib import admin

from .models import (
    Persona,
    Institucion,
    PeriodoAdministrativo,
    Legislatura,
    Cargo,
    MilitanciaPartidista,
    Relacion,
    Topic,
    InstitutionTopic,
    PersonTopicManual,
)


@admin.register(Persona)
class PersonaAdmin(admin.ModelAdmin):
    search_fields = ("nombre_completo",)
    prepopulated_fields = {"slug": ("nombre_completo",)}


@admin.register(Institucion)
class InstitucionAdmin(admin.ModelAdmin):
    search_fields = ("nombre",)
    list_filter = ("tipo", "ambito")
    prepopulated_fields = {"slug": ("nombre",)}


@admin.register(PeriodoAdministrativo)
class PeriodoAdministrativoAdmin(admin.ModelAdmin):
    list_display = ("nombre", "tipo", "nivel", "fecha_inicio", "fecha_fin")
    list_filter = ("tipo", "nivel")


@admin.register(Legislatura)
class LegislaturaAdmin(admin.ModelAdmin):
    list_display = ("nombre", "periodo")
    list_filter = ("periodo",)


@admin.register(Cargo)
class CargoAdmin(admin.ModelAdmin):
    list_display = (
        "persona",
        "nombre_cargo",
        "cargo_clase",
        "institucion",
        "periodo",
        "es_actual",
    )
    list_filter = ("cargo_clase", "institucion", "periodo", "es_actual")
    search_fields = ("nombre_cargo", "persona__nombre_completo")


@admin.register(MilitanciaPartidista)
class MilitanciaPartidistaAdmin(admin.ModelAdmin):
    list_display = ("persona", "partido", "fecha_inicio", "fecha_fin", "tipo")
    list_filter = ("partido", "tipo")
    search_fields = ("persona__nombre_completo", "partido__nombre")
    ordering = ("persona__nombre_completo", "-fecha_inicio")


@admin.register(Relacion)
class RelacionAdmin(admin.ModelAdmin):
    list_display = ("origen", "destino", "tipo")
    list_filter = ("tipo",)


@admin.register(Topic)
class TopicAdmin(admin.ModelAdmin):
    search_fields = ("name",)
    list_filter = ("topic_kind", "status")


@admin.register(InstitutionTopic)
class InstitutionTopicAdmin(admin.ModelAdmin):
    list_display = ("institution", "topic", "role")
    list_filter = ("topic",)


@admin.register(PersonTopicManual)
class PersonTopicManualAdmin(admin.ModelAdmin):
    list_display = ("person", "topic", "role")
