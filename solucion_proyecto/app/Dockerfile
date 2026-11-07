FROM python:3.12-slim

WORKDIR /app

# Instalar dependencias del sistema mínimas (incluyendo ffmpeg para extraer el audio real de videos MP4)
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    ffmpeg \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY src/ .
COPY escudos/ /app/escudos/
COPY iconos/ /app/iconos/
RUN mkdir -p /app/media /app/escudos /app/iconos

# Usuario no-root por seguridad (Lab 06: principio de mínimo privilegio en contenedores)
RUN useradd -m appuser && chown -R appuser:appuser /app
USER appuser

EXPOSE 8000

HEALTHCHECK --interval=15s --timeout=3s --start-period=5s --retries=3 \
  CMD curl -f http://localhost:8000/health || exit 1

# Gunicorn con workers gevent para soportar +1000 conexiones SSE concurrentes por réplica
CMD ["gunicorn", "--worker-class", "gevent", "--workers", "2", "--worker-connections", "1000", "--bind", "0.0.0.0:8000", "--timeout", "0", "app:app"]
