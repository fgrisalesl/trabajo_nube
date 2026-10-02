# 🚀 Proyecto del semestre

Equipos de **máximo 3 integrantes**. Un proyecto por equipo (sin repetir entre grupos). El mismo proyecto atraviesa arquitectura, desplegue, seguridad y costos. Al final debe estar **implementado y funcionando, no solo diagramado**.

## 🎯 Cómo arrancar (semana 5)
1. Conforman el equipo (**máximo 3 integrantes**) y **escogen un enunciado** de `enunciados/` (se asigna por orden de solicitud al docente).
2. Crean su repo desde [repo plantilla](https://github.com/cesarpalacios/gtn-plantilla-equipo) → *Use this template*.
3. Llenan la **ficha del caso** en su README y abren el issue *Hito 0*.

## 📅 Hitos semanales
| Sem | Hito | Entrega |
|---|---|---|
| 5 | Ficha del caso | Equipo, proyecto, caso, costo estimado del escenario |
| 6–7 | Servicio en línea | Servidor propio en AWS + app empaquetada en Docker |
| 9–10 | Arquitectura — **Nota 2 (20%)** | Diagrama, decisiones, revisión contra los 6 pilares |
| 11–12 | Automatización | Pipeline CI/CD + **todo el entorno en CloudFormation** |
| 13–14 | Seguridad y costos | Auditoría de permisos + informe FinOps (costo mensual optimizado) |
| 16 | Sustentación — **Nota 3 (20%)** | Demo en vivo defendida ante panel, desde el README del repo |

## 📦 Requisitos de la IaC (CloudFormation)
- Todo el entorno entregable en `iac/` como templates **YAML de CloudFormation** (pueden partir del ejemplo de la plantilla).
- Un template principal (idealmente anidado o con stacks por capa: red, cómputo, datos) con **Parámetros** y **Outputs**.
- **Tags obligatorios** en todos los recursos: `Curso: GTN-2026-2`, `Equipo: <nombre>`, `Proyecto: <número>`, `Ambiente: lab`.
- El entorno debe poder **reproducirse desde cero** con: `aws cloudformation deploy --template-file iac/main.yaml --stack-name gtn-<equipo> --capabilities CAPABILITY_NAMED_IAM`.
- Cada cambio de infraestructura pasa por **PR** (el CI corre `cfn-lint`).
- `iac/README.md` documenta cómo desplegar, detener y destruir el stack (y el costo estimado).

## 📖 Cómo se trabaja: caso → historias de usuario → backlog
Cada enunciado es un **caso real** con actores y **historias de usuario épicas** (`Como [rol], quiero [algo], para [valor]`). El flujo del equipo:
1. **Leen el caso** y lo discuten: ¿qué problema de negocio resuelve?
2. **Descomponen las épicas** en historias más pequeñas y las convierten en **issues de su repo** con la plantilla *Historia de usuario* (título `HU-XX`).
3. Cada historia lleva **criterios de aceptación** (Dado... Cuando... Entonces...) y se cierra con un **PR que la implementa**.
4. El tablero del repo muestra historias por estado (`Backlog → En curso → Hecho`) y los hitos semanales agrupan qué historias deben estar listas para cada entrega.
> La arquitectura nace de las historias: cada requisito no funcional (pico de carga, costo, disponibilidad) también se escribe como historia y justifica una decisión en `docs/decisiones.md`.
