from collections import Counter
from datetime import date
from typing import Dict, Optional, Tuple, List
from django.db.models import Q

from .models import Cargo, Persona, PeriodoAdministrativo, MilitanciaPartidista, Institucion


def partido_vigente_en_periodo(persona_id: int, periodo: PeriodoAdministrativo) -> Optional[Institucion]:
    qs = (
        MilitanciaPartidista.objects.filter(
            persona_id=persona_id,
            fecha_inicio__lte=periodo.fecha_fin,
        )
        .filter(Q(fecha_fin__isnull=True) | Q(fecha_fin__gte=periodo.fecha_inicio))
        .select_related("partido")
        .order_by("-fecha_inicio", "-id")
    )
    m = qs.first()
    return m.partido if m else None


def partido_vigente_en_fecha(
    persona_id: int,
    fecha: date,
    fallback_latest: bool = True,
) -> Optional[Institucion]:
    qs = (
        MilitanciaPartidista.objects.filter(
            persona_id=persona_id,
            fecha_inicio__lte=fecha,
        )
        .filter(Q(fecha_fin__isnull=True) | Q(fecha_fin__gte=fecha))
        .select_related("partido")
        .order_by("-fecha_inicio", "-id")
    )
    m = qs.first()
    if m:
        return m.partido
    if not fallback_latest:
        return None
    latest = (
        MilitanciaPartidista.objects.filter(persona_id=persona_id)
        .select_related("partido")
        .order_by("-fecha_inicio", "-id")
        .first()
    )
    return latest.partido if latest else None


def conteo_por_partido_en_periodo(periodo_id: int, cargo_clases: List[str]) -> Dict[str, int]:
    periodo = PeriodoAdministrativo.objects.get(id=periodo_id)

    persona_ids = (
        Cargo.objects.filter(periodo_id=periodo_id, cargo_clase__in=cargo_clases)
        .values_list("persona_id", flat=True)
        .distinct()
    )

    counter = Counter()
    for pid in persona_ids:
        partido = partido_vigente_en_periodo(pid, periodo)
        counter[partido.nombre if partido else "Sin partido"] += 1

    return dict(counter)


def migraciones_partidistas() -> List[Tuple[str, int]]:
    """
    Regresa lista simple: (nombre_persona, numero_de_cambios)
    """
    out = []
    for p in Persona.objects.all().only("id", "nombre_completo"):
        mils = list(
            MilitanciaPartidista.objects.filter(persona=p)
            .order_by("fecha_inicio", "id")
            .values_list("partido_id", flat=True)
        )
        # cambios = cuántas veces cambia el partido entre registros consecutivos
        changes = 0
        for a, b in zip(mils, mils[1:]):
            if a != b:
                changes += 1
        if changes > 0:
            out.append((p.nombre_completo, changes))
    out.sort(key=lambda x: x[1], reverse=True)
    return out
