# 🏷️ [NOMBRE DEL EQUIPO] — Proyecto [NN]

> **Ficha del caso** — reemplaza este archivo: es la carta de presentación de tu equipo y lo primero que verá el panel en la sustentación.

| Campo | Valor |
|---|---|
| Proyecto | [NN — nombre] |
| Integrantes | [nombres y códigos] |
| URL demo | https://... |
| Costo mensual real | USD ... (objetivo: USD ...) |
| Despliegue | `aws cloudformation deploy --template-file iac/main.yaml --stack-name gtn-[equipo] --capabilities CAPABILITY_NAMED_IAM` |

## 🏗️ Arquitectura
[Diagrama en docs/arquitectura.png — exporta tu diagrama y referéncialo aquí]

## 🔑 Decisiones (resumen — la tabla completa en docs/decisiones.md)
| Decisión | Elegimos | Alternativa descartada | Por qué |
|---|---|---|---|
| | | | |

## 💰 Costos
Ver `docs/costos.md` — estimado vs real y optimizaciones aplicadas.

## 🚀 Cómo levantar
1. `cd app && docker compose up --build` → local
2. `aws cloudformation deploy ...` → AWS (ver `iac/README.md`)
