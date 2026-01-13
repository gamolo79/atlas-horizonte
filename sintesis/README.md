# Síntesis

## Instalación

```bash
pip install -r requirements.txt
```

## Servicios requeridos

### Redis

```bash
redis-server
```

## Celery

Worker:

```bash
celery -A atlas_core worker -l info
```

Beat:

```bash
celery -A atlas_core beat -l info
```

## Django

```bash
python manage.py migrate
python manage.py runserver
```

## Troubleshooting

- Revisa los logs de Celery si los runs aparecen en estado `failed`.
- Verifica que `SINTESIS_ENABLE_PDF=true` y WeasyPrint estén instalados si el PDF no se genera.
- Asegura que `REDIS_URL` apunte al broker correcto.
