# Lab 03 — La App Viaja en Contenedor (Docker & Docker Swarm)

## 🎯 Objetivo
Empaquetar la aplicación del **Proyecto 06 (UNAL Sports Live)** en un contenedor Docker optimizado y desplegarla tanto en local como en la instancia EC2 de AWS Academy.

## 🐳 Mejoras de Producción aplicadas en `app/Dockerfile`
1. **Imagen ligera:** Basada en `python:3.12-slim` con instalación sin caché (`pip install --no-cache-dir`).
2. **Seguridad (Usuario No-Root):** Se crea el usuario `appuser` (`RUN useradd -m appuser && USER appuser`) para que el contenedor nunca corra como `root` en el host EC2.
3. **Alta Concurrencia SSE:** En lugar del servidor de desarrollo de Flask, el `CMD` ejecuta **Gunicorn con workers asíncronos `gevent`** (`--worker-class gevent --workers 2 --worker-connections 1000 --timeout 0`), permitiendo sostener más de 1,000 conexiones Server-Sent Events concurrentes.
4. **Autocuración (`HEALTHCHECK`):** Verifica cada 15 segundos `http://localhost:8000/health`.

## 🚀 Comandos de Verificación Ejecutados
```bash
cd app
docker compose up -d --build
docker ps
curl -i http://localhost:8000/health
```

- **Archivo versionado:** [`app/Dockerfile`](../app/Dockerfile) y [`app/docker-compose.yml`](../app/docker-compose.yml).
- **Captura de referencia:** `evidencias/lab03-docker-ps.png`.
