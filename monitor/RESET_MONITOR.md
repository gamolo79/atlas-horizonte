# Reset solo Monitor (Postgres)

## 1) Detener servicio
Detén el servicio Django/gunicorn y cualquier worker que use la base de datos.

## 2) Reset solo tablas Monitor en Postgres
Ejecuta el siguiente SQL en la base de datos:

```sql
DELETE FROM django_migrations WHERE app='monitor';

DO $$
DECLARE
    r RECORD;
BEGIN
    FOR r IN (
        SELECT tablename
        FROM pg_tables
        WHERE schemaname = 'public'
          AND tablename LIKE 'monitor_%'
    ) LOOP
        EXECUTE 'DROP TABLE IF EXISTS ' || quote_ident(r.tablename) || ' CASCADE';
    END LOOP;
END$$;
```

## 3) Re-crear migraciones desde cero (solo Monitor)
```bash
rm -f monitor/migrations/*.py
# volver a crear __init__.py
touch monitor/migrations/__init__.py
python manage.py makemigrations monitor
python manage.py migrate monitor
```

## 4) Validación
```bash
python manage.py check
python manage.py shell
```

En el shell:
```python
from monitor.models import Article, MediaSource
Article.objects.count()
MediaSource.objects.count()
```

## 5) UI
Navegar a `/monitor/dashboard/ingest/` y ejecutar los comandos.
