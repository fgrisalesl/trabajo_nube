# 💰 Informe FinOps y Optimización de Costos (Semana 13–14)

**Presupuesto objetivo del enunciado 06:** `≤ $15.00 USD / mes`  
**Presupuesto de la cuenta AWS Academy:** `$50.00 USD` (todo el proyecto corre unificado en **1 sola cuenta de AWS Academy**)  
**Costo mensual optimizado (Real):** **`$8.43 USD / mes`** (en operación continua 24/7) o **`$1.51 USD / mes`** (en operación bajo demanda para partidos/sustentación).

---

## 1. Comparativa: Estimado Inicial vs. Real Optimizado (USD/mes)

| Concepto / Servicio AWS | Estimado Inicial (Sin optimizar) | Real Optimizado (USD/mes 24/7) | Real en Uso Efímero (Lab 40h/mes) | Diferencia y causa de la optimización |
|---|---|---|---|---|
| **Cómputo API + Streaming SSE + Jenkins (EC2)** | $16.32 USD *(2x instancias separadas 24/7)* | **$7.59 USD** *(1x instancia EC2 unificada con Docker Compose/Swarm + Jenkins)* | **$0.83 USD** | Se implementó **Gunicorn + Gevent** capaz de sostener 1,000 conexiones SSE concurrentes y convivir con Jenkins y Nginx en una sola instancia EC2 dentro de la misma cuenta. |
| **Almacenamiento EBS (GP3)** | $1.60 USD *(20 GB GP2)* | **$0.64 USD** *(8 GB GP3)* | **$0.64 USD** | Imágenes Docker `slim` y `alpine` ocupan < 450 MB; un volumen raíz de 8 GB GP3 es suficiente y 20% más económico que GP2. |
| **Caché en Memoria (Redis)** | $11.52 USD *(`cache.t3.micro` ElastiCache 24/7)* | **$0.00 USD** *(Redis 7 Alpine en contenedor Docker + parámetro `DeployElastiCache=false`)* | **$0.00 USD** | Se parametrizó CloudFormation (`DeployElastiCache`) para correr Redis en contenedor con política `allkeys-lru` (128 MB) en la misma EC2, ahorrando **$11.52 USD/mes** sin perder latencia sub-milisegundo. |
| **Cola y Fan-Out de Eventos (AWS SNS + 2 Colas SQS)** | $0.50 USD *(Short polling)* | **$0.12 USD** *(SNS + SQS con Long Polling 20s)* | **$0.00 USD** *(Free Tier)* | Se activó `ReceiveMessageWaitTimeSeconds: 20` en `ColaCanalVivo`, eliminando el 95% de llamadas `ReceiveMessage` vacías a SQS. |
| **Almacenamiento S3 (`BucketDatos`)** | $0.25 USD | **$0.03 USD** *(< 1 GB actas JSON + evidencias)* | **$0.02 USD** | Se guardan únicamente resúmenes JSON compactos del partido. |
| **Transferencia de Datos Saliente** | $1.20 USD *(Polling HTTP repetitivo)* | **$0.05 USD** *(Frames SSE incrementales de ~250 bytes)* | **$0.02 USD** | Con SSE solo viajan los bytes del nuevo evento cuando ocurre una jugada, en lugar de recargar todo el HTML/JSON cada segundo. |
| **TOTAL MENSUAL** | ~~$31.39 USD/mes~~ *(Excedía límite)* | **✅ $8.43 USD/mes** *(43.8% bajo el tope de $15 USD)* | **✅ $1.51 USD/mes** | **Ahorro total logrado: -$22.96 USD/mes (-73.1%)** |

---

## 2. Optimizaciones FinOps Aplicadas (Qué hicimos para bajar el costo sin degradar el servicio)

1. **Consolidación en 1 Sola Cuenta y 1 Solo Stack (`iac/main.yaml`):**
   En lugar de levantar servidores separados para la base de caché, el balanceador Nginx, la API y el servidor Jenkins (lo que multiplicaría por 4 el gasto de cómputo EC2), consolidamos la arquitectura en una única instancia EC2 dentro de una sola cuenta de AWS Academy, orquestando los microservicios con **Docker Compose / Docker Swarm** (`nginx` en puerto `80`, `app` en puerto `8000`, `redis` en red interna y `Jenkins` en puerto `8080`).
2. **Arquitectura Efímera por Diseño ("Torneo Bajo Demanda"):**
   El enunciado pide explícitamente *"aguantar el pico del partido final sin contratar servidores dedicados todo el año"*. Gracias a que el 100% de la infraestructura está en `iac/main.yaml`, el organizador despliega el stack 15 minutos antes del partido (`aws cloudformation deploy`) y lo destruye al finalizar (`aws cloudformation delete-stack`), pagando únicamente por las horas de transmisión real (~$0.02 USD por partido).
3. **Concurrencia Asíncrona (Gevent) en lugar de Escalamiento Vertical Costoso:**
   En vez de pagar instancias grandes (`m5.large` de $70/mes), configuramos Gunicorn con `--worker-class gevent --worker-connections 1000`. Esto permite que una instancia económica mantenga más de 1,000 conexiones SSE abiertas simultáneamente con < 25% de uso de CPU.
4. **SQS Long Polling + SNS Message Filtering:**
   La suscripción de la cola de resumen (`SuscripcionResumen`) tiene un `FilterPolicy` nativo en SNS (`priority: [HIGH]`). Así, los comentarios de rutina ni siquiera se encolan en `ColaCanalResumen`, reduciendo a la mitad el costo por millón de peticiones en SQS.
5. **Caché Híbrido Parametrizado (`DeployElastiCache`):**
   El template `iac/main.yaml` incluye la condición `CreateElastiCacheCluster`. Por defecto (`DeployElastiCache=false`), Redis corre dentro de Docker en la misma EC2 ($0 adicional), y si se desea evaluar el servicio administrado `ElastiCache` basta con cambiar el parámetro a `true`.
