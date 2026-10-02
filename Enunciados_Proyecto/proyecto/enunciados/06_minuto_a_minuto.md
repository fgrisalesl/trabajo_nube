# 06 · Minuto a minuto de torneos deportivos
## 📖 El caso
La liga universitaria transmite resultados por un grupo de WhatsApp que se satura en los partidos clave: miles leyendo y solo un periodista escribiendo. Quieren una página de minuto a minuto que aguante el pico del partido final sin contratar servidores dedicados todo el año.
## 👥 Actores
Periodista (reporta eventos) · Aficionado (sigue en vivo) · Organizador de la liga
## 📝 Historias de usuario (épicas iniciales)
- **[HU-01]** Como periodista, quiero reportar gol/tarjeta/cambio desde el celular, para actualizar en segundos.
- **[HU-02]** Como aficionado, quiero ver los eventos del partido en vivo sin recargar, para seguirlo desde la tribuna.
- **[HU-03]** Como aficionado, quiero el resumen del partido cuando entro tarde, para ponerme al día rápido.
- **[HU-04]** Como organizador, quiero que el sistema aguante 1000 lectores simultáneos, para el partido final.
## ☁️ Requisitos cloud
EC2/ECS (API) · SQS o SNS (cola de eventos) · ElastiCache o CloudFront (caché) · **CloudFormation**
## ⚠️ Restricciones
Simulador de carga incluido · **presupuesto objetivo ≤ 15 USD/mes** · métricas de latencia bajo pico
## ✅ Entregables clave
Endpoint de eventos en vivo · demo del pico con simulador · explicación del patrón fan-out elegido
## 🚀 Reto extra
Canal "vivo" y canal "resumen" con prioridad distinta.
