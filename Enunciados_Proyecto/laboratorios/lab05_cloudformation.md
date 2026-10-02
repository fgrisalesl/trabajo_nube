# Lab 05 — Todo el entorno en CloudFormation
**Objetivo:** infraestructura reproducible desde código (hito de la semana 12).
**Pasos:** partir de `iac/main.yaml` → convertir TODA su infra en template(s) → validar con `cfn-lint` → desplegar con `aws cloudformation deploy` → destruir y volver a desplegar desde cero (prueba de reproducibilidad).
**Evidencia:** captura del stack CREATE_COMPLETE + tiempos de destruir/recrear + `iac/` completo en su repo.
