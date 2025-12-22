from django.db import models

from atlas_core.text_utils import normalize_name


class Persona(models.Model):
    nombre_completo = models.CharField(max_length=255)
    nombre_normalizado = models.CharField(max_length=255, blank=True, db_index=True)
    slug = models.SlugField(max_length=255, unique=True)
    fecha_nacimiento = models.DateField(null=True, blank=True)
    lugar_nacimiento = models.CharField(max_length=255, blank=True)
    bio_corta = models.TextField(blank=True)

    class Meta:
        ordering = ["nombre_completo"]

    def save(self, *args, **kwargs):
        self.nombre_normalizado = normalize_name(self.nombre_completo)
        super().save(*args, **kwargs)

    def __str__(self):
        return self.nombre_completo


class Institucion(models.Model):
    TIPO_INSTITUCION = [
        ("publica", "Pública"),
        ("privada", "Privada"),
        ("social", "Social / ONG"),
        ("educativa", "Educativa"),
        ("partido", "Partido político"),
        ("otro", "Otro"),
    ]

    nombre = models.CharField(max_length=255)
    nombre_normalizado = models.CharField(max_length=255, blank=True, db_index=True)
    slug = models.SlugField(max_length=255, unique=True)
    tipo = models.CharField(
        max_length=20,
        choices=TIPO_INSTITUCION,
        default="publica",
    )
    ambito = models.CharField(
        max_length=100,
        blank=True,
        help_text="Municipal, estatal, federal, regional, nacional, etc.",
    )
    ciudad = models.CharField(max_length=100, blank=True)
    estado = models.CharField(max_length=100, blank=True)
    pais = models.CharField(max_length=100, default="México")

    # Institución padre (jerarquía)
    padre = models.ForeignKey(
        "self",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="hijas",
        help_text="Institución de la cual depende (ej. Municipio, Poder Ejecutivo, Ayuntamiento).",
    )

    # Nota: Las instituciones NO representan periodos administrativos.
    # Los periodos (sexenios, trienios, legislaturas, etc.) deben modelarse
    # con PeriodoAdministrativo para evitar duplicar el árbol institucional.

    class Meta:
        ordering = ["nombre"]

    def save(self, *args, **kwargs):
        self.nombre_normalizado = normalize_name(self.nombre)
        super().save(*args, **kwargs)

    def __str__(self):
        if self.padre:
            return f"{self.nombre} ({self.padre.nombre})"
        return self.nombre


class PeriodoAdministrativo(models.Model):
    """
    Periodos administrativos independientes de las instituciones.

    Los periodos NO forman parte del árbol institucional y sólo se usan para
    clasificar, filtrar y agrupar cargos, legislaturas y reportes.
    """

    TIPO_CHOICES = [
        ("SEXENIO", "Sexenio"),
        ("TRIENIO", "Trienio"),
        ("LEGISLATURA", "Legislatura"),
        ("PROCESO_ELECTORAL", "Proceso electoral"),
    ]

    NIVEL_CHOICES = [
        ("ESTATAL", "Estatal"),
        ("MUNICIPAL", "Municipal"),
        ("LEGISLATIVO", "Legislativo"),
    ]

    tipo = models.CharField(max_length=20, choices=TIPO_CHOICES)
    nivel = models.CharField(max_length=20, choices=NIVEL_CHOICES)
    nombre = models.CharField(max_length=100, unique=True)
    fecha_inicio = models.DateField()
    fecha_fin = models.DateField()
    institucion_raiz = models.ForeignKey(
        "Institucion",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="periodos",
        help_text="Institución raíz asociada (ej. Estado de Sonora).",
    )

    class Meta:
        ordering = ["fecha_inicio"]

    def __str__(self):
        return self.nombre


class Legislatura(models.Model):
    """
    Legislaturas separadas del árbol institucional.

    Deben vincularse a PeriodoAdministrativo (tipo=LEGISLATURA).
    """

    nombre = models.CharField(max_length=100)
    numero = models.PositiveIntegerField(null=True, blank=True)
    periodo = models.ForeignKey(
        PeriodoAdministrativo,
        on_delete=models.PROTECT,
        related_name="legislaturas",
        limit_choices_to={"tipo": "LEGISLATURA"},
    )
    notas = models.TextField(blank=True)

    class Meta:
        ordering = ["periodo__fecha_inicio", "nombre"]
        unique_together = ("periodo", "nombre")

    def __str__(self):
        return self.nombre


class Cargo(models.Model):
    persona = models.ForeignKey(
        Persona,
        on_delete=models.CASCADE,
        related_name="cargos",
    )
    institucion = models.ForeignKey(
        Institucion,
        on_delete=models.CASCADE,
        related_name="cargos",
    )
    periodo = models.ForeignKey(
        PeriodoAdministrativo,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="cargos",
        help_text=(
            "Periodo administrativo asociado (sexenio, trienio, legislatura, etc.)."
        ),
    )
    nombre_cargo = models.CharField(max_length=255)
    fecha_inicio = models.DateField(null=True, blank=True)
    fecha_fin = models.DateField(null=True, blank=True)
    es_actual = models.BooleanField(default=False)
    notas = models.TextField(blank=True)

    class Meta:
        ordering = ["-fecha_inicio", "persona"]

    def __str__(self):
        return f"{self.nombre_cargo} – {self.persona.nombre_completo}"


class Relacion(models.Model):
    TIPO_RELACION = [
        ("familiar", "Relación familiar"),
        ("amistad", "Amistad / cercanía personal"),
        ("socio", "Socios / negocios"),
        ("grupo_politico", "Mismo grupo político"),
        ("laboral", "Relación laboral"),
        ("otro", "Otro tipo de relación"),
    ]

    origen = models.ForeignKey(
        Persona,
        on_delete=models.CASCADE,
        related_name="relaciones_origen",
    )
    destino = models.ForeignKey(
        Persona,
        on_delete=models.CASCADE,
        related_name="relaciones_destino",
    )
    tipo = models.CharField(max_length=50, choices=TIPO_RELACION, default="otro")
    descripcion = models.TextField(blank=True)
    fuente = models.CharField(max_length=255, blank=True)

    class Meta:
        verbose_name = "Relación"
        verbose_name_plural = "Relaciones"

    def __str__(self):
        return f"{self.origen} → {self.destino} ({self.tipo})"
