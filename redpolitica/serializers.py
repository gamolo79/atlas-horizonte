from django.utils import timezone
from rest_framework import serializers

from .models import (
    Persona,
    Institucion,
    Cargo,
    Relacion,
    PeriodoAdministrativo,
    MilitanciaPartidista,
)
from .utils_grafos import partido_vigente_en_fecha


class PeriodoAdministrativoSerializer(serializers.ModelSerializer):
    class Meta:
        model = PeriodoAdministrativo
        fields = [
            "id",
            "tipo",
            "nivel",
            "nombre",
            "fecha_inicio",
            "fecha_fin",
        ]


class InstitucionSerializer(serializers.ModelSerializer):
    class Meta:
        model = Institucion
        fields = [
            "id",
            "nombre",
            "slug",
            "tipo",
            "ambito",
            "ciudad",
            "estado",
            "pais",
            "padre",         # <- ID de la institución padre
        ]


class CargoSerializer(serializers.ModelSerializer):
    institucion = InstitucionSerializer()
    periodo = PeriodoAdministrativoSerializer(allow_null=True)
    periodo_id = serializers.IntegerField(source="periodo.id", read_only=True)
    periodo_nombre = serializers.CharField(source="periodo.nombre", read_only=True)
    periodo_tipo = serializers.CharField(source="periodo.tipo", read_only=True)
    periodo_nivel = serializers.CharField(source="periodo.nivel", read_only=True)

    class Meta:
        model = Cargo
        fields = [
            "id",
            "nombre_cargo",
            "institucion",
            "periodo",
            "periodo_id",
            "periodo_nombre",
            "periodo_tipo",
            "periodo_nivel",
            "fecha_inicio",
            "fecha_fin",
            "es_actual",
            "notas",
        ]


class PersonaSerializer(serializers.ModelSerializer):
    cargos = CargoSerializer(many=True, read_only=True)

    class Meta:
        model = Persona
        fields = [
            "id",
            "nombre_completo",
            "slug",
            "fecha_nacimiento",
            "lugar_nacimiento",
            "bio_corta",
            "cargos",
        ]


class MilitanciaPartidistaSerializer(serializers.ModelSerializer):
    partido_id = serializers.IntegerField(source="partido.id", read_only=True)
    partido_nombre = serializers.CharField(source="partido.nombre", read_only=True)

    class Meta:
        model = MilitanciaPartidista
        fields = [
            "partido_id",
            "partido_nombre",
            "fecha_inicio",
            "fecha_fin",
            "tipo",
            "notas",
        ]


class PersonaGrafoSerializer(PersonaSerializer):
    partido_principal = serializers.SerializerMethodField()
    militancias = serializers.SerializerMethodField()

    class Meta(PersonaSerializer.Meta):
        fields = PersonaSerializer.Meta.fields + [
            "partido_principal",
            "militancias",
        ]

    def get_partido_principal(self, obj):
        today = timezone.now().date()
        partido = partido_vigente_en_fecha(obj.id, today)
        return partido.nombre if partido else None

    def get_militancias(self, obj):
        militancias = (
            obj.militancias.select_related("partido")
            .order_by("-fecha_inicio", "-id")
        )
        return MilitanciaPartidistaSerializer(militancias, many=True).data


class RelacionSerializer(serializers.ModelSerializer):
    origen = serializers.PrimaryKeyRelatedField(read_only=True)
    destino = serializers.PrimaryKeyRelatedField(read_only=True)

    class Meta:
        model = Relacion
        fields = ["id", "origen", "destino", "tipo", "descripcion", "fuente"]
