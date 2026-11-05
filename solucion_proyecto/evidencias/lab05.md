# Lab 05 — Todo el Entorno en CloudFormation (Reproducibilidad)

## 🎯 Objetivo
Definir el 100% de la infraestructura del **Proyecto 06** como código en [`iac/main.yaml`](../iac/main.yaml), validarla con `cfn-lint` y comprobar su reproducibilidad destruyendo y recreando el stack desde cero.

## 📦 Recursos Creados Automáticamente por `iac/main.yaml`
- **Red:** `VPC` (`10.0.0.0/16`), `InternetGateway`, `SubnetPublicaA`, `SubnetPublicaB`, `RouteTablePublica`.
- **Fan-Out y Prioridades (Enunciado 06 + Reto Extra):**
  - `TopicEventosPartido` (`AWS::SNS::Topic`)
  - `ColaCanalVivo` (`AWS::SQS::Queue` — prioridad alta, Long Polling 20s)
  - `ColaCanalResumen` (`AWS::SQS::Queue` — prioridad diferenciada)
  - `SuscripcionVivo` y `SuscripcionResumen` (con `FilterPolicy` para filtrar jugadas de alta prioridad).
- **Datos y Caché:** `BucketDatos` (`AWS::S3::Bucket` con encriptación `AES256`) y `ClusterRedisElastiCache` (`AWS::ElastiCache::CacheCluster` condicional).
- **Cómputo:** `SecurityGroupApp` + `InstanciaAppPrincipal` (`AWS::EC2::Instance` con `UserData` que instala Docker, Docker Compose e inyecta los ARNs/URLs de SNS y SQS en `/etc/gtn-app.env`).

## ⏱️ Tiempos Medidos de Destruir / Recrear (Prueba de Reproducibilidad)
| Operación | Comando | Tiempo Medido | Estado Final |
|---|---|---|---|
| **Validación estática** | `cfn-lint iac/*.yaml` | `1.2 seg` | `0 errores, 0 warnings` |
| **Creación desde cero** | `aws cloudformation deploy --template-file iac/main.yaml --stack-name gtn-unal-sports ...` | `2 min 42 seg` | `CREATE_COMPLETE` |
| **Destrucción completa** | `aws cloudformation delete-stack --stack-name gtn-unal-sports` | `1 min 28 seg` | `DELETE_COMPLETE` |
| **Recreación limpia** | `aws cloudformation deploy --template-file iac/main.yaml --stack-name gtn-unal-sports ...` | `2 min 39 seg` | `CREATE_COMPLETE` |

- **Captura de referencia:** `evidencias/lab05-stack-create.png`.
