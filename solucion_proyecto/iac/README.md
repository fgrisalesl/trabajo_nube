# ☁️ Infraestructura como Código (IaC) — AWS CloudFormation (`iac/main.yaml`)

Toda la infraestructura del **Proyecto 06: Minuto a minuto de torneos deportivos** se despliega en **una sola cuenta de AWS Academy** mediante el template único [`iac/main.yaml`](./main.yaml), cumpliendo al 100% los requisitos del curso:
- **Un único comando reproducible** (`aws cloudformation deploy`).
- **Parámetros** para todo valor configurable (`NombreEquipo`, `Ambiente`, `InstanceType`, `DeployElastiCache`).
- **Outputs** exportando VPC, Bucket S3, Topic SNS, Colas SQS, URL de la Demo (`Puerto 80`) y URL de Jenkins (`Puerto 8080`).
- **Tags obligatorios** en todos los recursos: `Curso: GTN-2026-2`, `Equipo`, `Proyecto: proyecto-06`, `Ambiente: lab`.

---

## 📦 ¿Qué crea automáticamente `iac/main.yaml` en tu cuenta de AWS?

| Capa | Recursos CloudFormation creados | Propósito en el Proyecto 06 |
|---|---|---|
| **1. Red (`VPC`)** | `VPC` (`10.0.0.0/16`), `InternetGateway`, `SubnetPublicaA`, `SubnetPublicaB`, `RouteTablePublica` | Red aislada con salida a Internet y soporte multi-AZ. |
| **2. Patrón Fan-Out y Prioridades** | `TopicEventosPartido` (`AWS::SNS::Topic`) + `ColaCanalVivo` (`AWS::SQS::Queue`) + `ColaCanalResumen` (`AWS::SQS::Queue`) + `SuscripcionResumen` (`FilterPolicy: priority=HIGH`) | Recibe 1 evento del periodista y lo bifurca automáticamente entre el canal en vivo (alta prioridad) y el canal resumen (solo jugadas determinantes — **Reto Extra**). |
| **3. Caché y Datos** | `BucketDatos` (`AWS::S3::Bucket` con cifrado `AES256`) + `ClusterRedisElastiCache` (condicional con `DeployElastiCache`) | Respaldo encriptado de actas del partido y caché en memoria `O(1)` para quienes entran tarde (`HU-03`). |
| **4. Cómputo + CQRS + CI/CD Unificado** | `SecurityGroupApp` (`80`, `8000`, `8001`, `8080`, `22`) + `InstanciaAppPrincipal` (`AWS::EC2::Instance` con `LabInstanceProfile`) | Servidor EC2 todo-en-uno con **Docker**, **Docker Compose / Swarm** (separando el contenedor `fan-portal` en `8000` y `journalist-studio` en `8001`), **Jenkins CI/CD (puerto 8080)** y `/etc/gtn-app.env` preconfigurado. |

---

## ✅ 1. Validar la plantilla antes de cada Pull Request

```bash
pip install cfn-lint
cfn-lint iac/*.yaml
```

---

## 🚀 2. Cómo desplegar todo desde cero con un solo comando (Lab 05)

En la terminal de **AWS CloudShell** (o tu terminal local configurada con las credenciales de AWS Academy):

```bash
aws cloudformation deploy \
  --template-file iac/main.yaml \
  --stack-name gtn-unal-sports \
  --capabilities CAPABILITY_NAMED_IAM \
  --parameter-overrides \
    NombreEquipo=unal-sports \
    Ambiente=lab \
    ProyectoId=proyecto-06 \
    InstanceType=t3.small \
    DeployElastiCache=false
```

Consultar las URLs públicas generadas (`DemoURL` en puerto 80 y `JenkinsURL` en puerto 8080):
```bash
aws cloudformation describe-stacks \
  --stack-name gtn-unal-sports \
  --query "Stacks[0].Outputs" \
  --output table
```

---

## 🛑 3. Cómo destruir el stack al terminar cada sesión de trabajo (FinOps)

Para cuidar los **$50 USD de la cuenta de AWS Academy**, destruyan el stack al terminar su sesión de clase o pruebas:

```bash
# 1. Vaciar el bucket S3 si tiene archivos:
BUCKET=$(aws cloudformation describe-stacks --stack-name gtn-unal-sports --query "Stacks[0].Outputs[?OutputKey=='BucketDatos'].OutputValue" --output text)
aws s3 rm s3://$BUCKET --recursive

# 2. Eliminar el stack completo:
aws cloudformation delete-stack --stack-name gtn-unal-sports
aws cloudformation wait stack-delete-complete --stack-name gtn-unal-sports
```
- **Tiempo promedio de creación (`CREATE_COMPLETE`)**: ~2 min 45 seg.
- **Tiempo promedio de destrucción (`DELETE_COMPLETE`)**: ~1 min 30 seg.

---

## 💰 4. Costo mensual estimado del Stack

| Recurso CloudFormation | Configuración | Costo Mensual (Uso 24/7 con `t3.micro`) | Costo en Uso Académico (40h/mes) |
|---|---|---|---|
| `AWS::EC2::Instance` | `t3.micro` / `t3.small` + 8 GB EBS `gp3` | $8.23 USD | $1.10 USD |
| `AWS::SNS::Topic` | ~100,000 publicaciones Fan-Out / mes | $0.05 USD | $0.00 USD *(Free Tier)* |
| `AWS::SQS::Queue` (x2) | `ColaCanalVivo` + `ColaCanalResumen` | $0.12 USD | $0.00 USD *(Free Tier)* |
| `AWS::S3::Bucket` | `< 1 GB` con cifrado AES-256 | $0.03 USD | $0.01 USD |
| `Redis Cache` | En contenedor Docker (`DeployElastiCache=false`) | $0.00 USD | $0.00 USD |
| **TOTAL MENSUAL** | **Cumple restricción ≤ $15.00 USD/mes** | **✅ $8.43 USD / mes** | **✅ $1.11 USD / mes** |
