# Monitor Horizonte (reconstrucción desde cero)

## Arquitectura modular

```
[Ingesta] -> [Normalización/Limpieza] -> [Clasificación IA]
     -> [Agregación de métricas] -> [Historias/Clustering]
     -> [Síntesis diaria] -> [Dashboards/Benchmarks]
     -> [Entrenamiento/Auditoría]
```

### Módulos

- **Ingesta** (`monitor.pipeline.ingest_sources`): ingesta de fuentes configuradas, deduplicación con `hash_dedupe` y `url`.
- **Normalización/Limpieza** (`monitor.pipeline.normalize_articles`): limpieza de HTML y versionado (`ArticleVersion`).
- **Clasificación IA** (`monitor.pipeline.classify_articles`): crea `ClassificationRun`, `Extraction` y `DecisionTrace` (explicable).
- **Agregación** (`monitor.pipeline.aggregate_metrics`): recalcula `MetricAggregate` por actor/tema.
- **Historias** (`monitor.pipeline.cluster_stories`): agrupa artículos por ventana temporal y tema (`Story`, `StoryArticle`).
- **Síntesis diaria** (`monitor.pipeline.build_daily_digest`): genera `DailyExecution` y `DailyDigestItem` por cliente.
- **Entrenamiento/Auditoría** (`Correction`, `TrainingExample`, `AuditLog`): solo aprende de correcciones humanas.

### Flujos principales

1. **Ingesta**: `monitor_ingest` crea artículos con status `ingested`.
2. **Normalización + Clasificación**: `monitor_analyze` limpia y clasifica con salidas JSON explicables.
3. **Clustering**: `monitor_cluster` crea historias.
4. **Agregación**: `monitor_aggregate` recalcula métricas.
5. **Síntesis diaria**: `monitor_build_digest` genera propuesta editorial.
6. **Correcciones**: UI para editar artículo/historia con explicación editorial; genera `TrainingExample`.

### Observabilidad

- Logs estructurados con `AuditLog`.
- Ejecuciones de jobs con `JobLog`.

### Configuración de `Source.config`

`Source.config` define cómo extraer URLs y contenido real según `Source.source_type`.

- **RSS**
  - `entry_limit` (int, opcional): máximo de items por fuente (por defecto usa `--limit`).
- **Sitemap**
  - `sitemap_urls` (list[str], opcional): lista de sitemaps (si no se especifica usa `Source.url`).
- **HTML**
  - `list_url` (str, opcional): URL con listado de notas (por defecto `Source.url`).
  - `link_selector` (str, opcional): selector CSS para encontrar links.
  - `link_attr` (str, opcional): atributo del link (por defecto `href`).
  - Si no hay `link_selector`, se toma `list_url` como URL directa de artículo.
- **API**
  - `endpoint` (str, opcional): endpoint JSON (por defecto `Source.url`).
  - `items_path` (str, opcional): ruta separada por puntos para llegar al array de items (ej. `data.items`).
  - `url_field`, `title_field`, `lead_field`, `body_field`, `published_field` (str, opcional).
  - `body_is_html` (bool, opcional): si el body viene en HTML, se guarda como `raw_html` y se normaliza.

### APIs

- `POST /monitor/api/jobs/ingest/`
- `POST /monitor/api/jobs/analyze/`
- `POST /monitor/api/jobs/cluster/`
- `POST /monitor/api/jobs/digest/`

### UI mínima

- `GET /monitor/ingest/`
- `GET /monitor/articles/<id>/`
- `GET /monitor/stories/<id>/`
- `GET /monitor/dashboard/`
- `GET /monitor/benchmarks/`

### Plan de migración mínima

`monitor_migrate_legacy` copia fuentes y artículos válidos desde tablas legadas (`monitor_mediasource`, `monitor_article`) y descarta parches/embeddings.

---

## Pasos de ejecución (humano)
1. detener servicio
2. reset tablas monitor
3. borrar migraciones monitor y recrear
4. migrate
5. start servicio
6. probar UI ingest
