from django.contrib import admin

from monitor.models import InstitucionAlias, PersonaAlias

from .models import (
    Persona,
    Institucion,
    Cargo,
    Relacion,
    PeriodoAdministrativo,
    Legislatura,
)


class PersonaAliasInline(admin.TabularInline):
    model = PersonaAlias
    extra = 1
    fields = ("alias",)


class InstitucionAliasInline(admin.TabularInline):
    model = InstitucionAlias
    extra = 1
    fields = ("alias",)


@admin.register(Persona)
class PersonaAdmin(admin.ModelAdmin):
    list_display = ("nombre_completo", "fecha_nacimiento", "lugar_nacimiento")
    search_fields = ("nombre_completo", "slug", "lugar_nacimiento")
    prepopulated_fields = {"slug": ("nombre_completo",)}
    inlines = (PersonaAliasInline,)


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
    inlines = (InstitucionAliasInline,)


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
