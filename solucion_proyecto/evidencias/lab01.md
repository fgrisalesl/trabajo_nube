# Lab 01 — Consola AWS y Calculadora de Costos

## 🎯 Objetivo
Identificar los servicios cloud requeridos por el **Proyecto 06 (Minuto a minuto de torneos deportivos)** y estimar el escenario mensual en **AWS Pricing Calculator** cumpliendo la restricción de **≤ 15.00 USD/mes**.

## 📊 Tabla de Servicios y Estimación Mensual (`us-east-1`)

| Servicio AWS | Rol en el Proyecto 06 | Configuración seleccionada | Costo Mensual Estimado (24/7) | Costo en Uso Académico (40h/mes) |
|---|---|---|---|---|
| **Amazon EC2** | Servidor API Flask/Gunicorn + Gateway Nginx SSE + Clúster Docker Swarm | 1x `t3.micro` (2 vCPU, 1 GB RAM, Linux, On-Demand) + 8 GB EBS `gp3` | **$8.23 USD** | **$1.10 USD** |
| **Amazon SNS** | Tópico de entrada para el patrón Fan-Out (`gtn-unal-sports-eventos-partido`) | 100,000 publicaciones HTTP/SQS al mes | **$0.05 USD** | **$0.00 USD** *(Free Tier)* |
| **Amazon SQS** | 2 Colas desacopladas (`ColaCanalVivo` prioridad alta y `ColaCanalResumen` prioridad baja) | 500,000 peticiones/mes con Long Polling (20s) | **$0.12 USD** | **$0.00 USD** *(Free Tier 1M req)* |
| **Amazon ElastiCache / Redis** | Caché en memoria O(1) para `/api/summary` (usuarios que entran tarde) y Pub/Sub | Redis 7 Alpine en contenedor Docker (`DeployElastiCache=false` por defecto; `cache.t3.micro` opcional) | **$0.00 USD** *(en contenedor)* | **$0.00 USD** |
| **Amazon S3** | Almacenamiento de actas del torneo y respaldos JSON encriptados (`AES256`) | 1 GB Standard + 2,000 PUT / 10,000 GET | **$0.03 USD** | **$0.01 USD** |
| **TOTAL MENSUAL** | **Arquitectura completa Minuto a Minuto** | **Región `us-east-1` (N. Virginia)** | **✅ $8.43 USD / mes** | **✅ $1.11 USD / mes** |

- **Presupuesto objetivo del enunciado 06:** `≤ $15.00 USD / mes`.
- **Margen de ahorro logrado:** `$6.57 USD / mes` por debajo del límite máximo (43.8% de ahorro).
- **Captura de referencia:** `evidencias/lab01-pricing-calculator.png`.
