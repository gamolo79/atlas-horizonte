from django.db import models
from django.db.models.signals import post_save
from django.dispatch import receiver
from django.utils.text import slugify

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
        ("FEDERAL", "Federal"),
    ]

    tipo = models.CharField(max_length=20, choices=TIPO_CHOICES)
    nivel = models.CharField(max_length=20, choices=NIVEL_CHOICES)
    nombre = models.CharField(max_length=100, unique=True)
    fecha_inicio = models.DateField()
    fecha_fin = models.DateField()

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


def _create_relaciones_laborales(cargo):
    if not cargo.periodo_id or not cargo.institucion_id or not cargo.persona_id:
        return

    try:
        institucion = cargo.institucion
        periodo = cargo.periodo
    except (Institucion.DoesNotExist, PeriodoAdministrativo.DoesNotExist):
        return

    parent_institucion = institucion.padre
    if parent_institucion:
        parent_cargos = Cargo.objects.filter(
            institucion=parent_institucion,
            periodo=periodo,
        ).select_related("persona", "institucion")
        child_cargos = [cargo]
        _build_relaciones_laborales(parent_cargos, child_cargos, periodo)

    child_cargos = Cargo.objects.filter(
        institucion__padre=institucion,
        periodo=periodo,
    ).select_related("persona", "institucion")
    _build_relaciones_laborales([cargo], child_cargos, periodo)


def _build_relaciones_laborales(parent_cargos, child_cargos, periodo):
    for parent_cargo in parent_cargos:
        for child_cargo in child_cargos:
            if parent_cargo.persona_id == child_cargo.persona_id:
                continue
            Relacion.objects.get_or_create(
                origen=parent_cargo.persona,
                destino=child_cargo.persona,
                tipo="laboral",
                defaults={
                    "descripcion": (
                        "Relación laboral por periodo "
                        f"{periodo.nombre} entre {parent_cargo.institucion.nombre} "
                        f"y {child_cargo.institucion.nombre}."
                    )
                },
            )


@receiver(post_save, sender=Cargo)
def cargo_post_save(sender, instance, **kwargs):
    _create_relaciones_laborales(instance)


class Topic(models.Model):
    TOPIC_KIND_CHOICES = [
        ("public_function", "Función Pública"),
        ("private_objective", "Objetivo Privado"),
        ("cross_cutting", "Transversal"),
    ]
    STATUS_CHOICES = [
        ("active", "Activo"),
        ("archived", "Archivado"),
    ]

    name = models.CharField(max_length=150, unique=True)
    slug = models.SlugField(max_length=150, unique=True, blank=True)
    description = models.TextField(blank=True, null=True)
    parent = models.ForeignKey(
        "self",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="children",
    )
    topic_kind = models.CharField(
        max_length=40,
        choices=TOPIC_KIND_CHOICES,
        default="cross_cutting",
    )
    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default="active",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name"]
        indexes = [
            models.Index(fields=["slug"]),
            models.Index(fields=["name"]),
            models.Index(fields=["topic_kind", "status"]),
        ]

    def save(self, *args, **kwargs):
        if not self.slug:
            base_slug = slugify(self.name)[:150]
            slug = base_slug or "tema"
            counter = 2
            while Topic.objects.filter(slug=slug).exclude(pk=self.pk).exists():
                suffix = f"-{counter}"
                slug = f"{base_slug[:150 - len(suffix)]}{suffix}"
                counter += 1
            self.slug = slug
        super().save(*args, **kwargs)

    def __str__(self):
        return self.name


class InstitutionTopic(models.Model):
    institution = models.ForeignKey(
        Institucion,
        on_delete=models.CASCADE,
        related_name="temas_relacionados",
    )
    topic = models.ForeignKey(
        Topic,
        on_delete=models.CASCADE,
        related_name="institution_links",
    )
    role = models.CharField(max_length=100)
    note = models.TextField(blank=True, null=True)
    valid_from = models.DateField(blank=True, null=True)
    valid_to = models.DateField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["institution", "topic", "role"],
                name="uniq_institution_topic_role",
            )
        ]
        ordering = ["topic", "institution", "role"]

    def __str__(self):
        return f"{self.institution} · {self.topic} ({self.role})"


class PersonTopicManual(models.Model):
    person = models.ForeignKey(
        Persona,
        on_delete=models.CASCADE,
        related_name="temas_manual",
    )
    topic = models.ForeignKey(
        Topic,
        on_delete=models.CASCADE,
        related_name="person_links",
    )
    role = models.CharField(max_length=100)
    note = models.TextField(blank=True, null=True)
    source_url = models.URLField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["person", "topic", "role"],
                name="uniq_person_topic_role",
            )
        ]
        ordering = ["topic", "person", "role"]

    def __str__(self):
        return f"{self.person} · {self.topic} ({self.role})"
