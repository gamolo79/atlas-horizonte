from rest_framework import serializers
from .models import Persona, Institucion, Cargo, Relacion, PeriodoAdministrativo


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

    class Meta:
        model = Cargo
        fields = [
            "id",
            "nombre_cargo",
            "institucion",
            "periodo",
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


class RelacionSerializer(serializers.ModelSerializer):
    origen = serializers.PrimaryKeyRelatedField(read_only=True)
    destino = serializers.PrimaryKeyRelatedField(read_only=True)

    class Meta:
        model = Relacion
        fields = ["id", "origen", "destino", "tipo", "descripcion", "fuente"]
