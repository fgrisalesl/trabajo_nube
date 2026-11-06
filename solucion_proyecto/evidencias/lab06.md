# Lab 06 — Auditoría de Seguridad del Propio Proyecto

## 🎯 Objetivo
Auditar la arquitectura, los contenedores y las plantillas CloudFormation del **Proyecto 06** frente a los controles de IAM, puertos, encriptación en tránsito/reposo y manejo de secretos, corrigiendo cada hallazgo mediante código versionado.

## 🛡️ Tabla de Hallazgos → Correcciones Aplicadas

| # | Categoría | Hallazgo Inicial (Riesgo detectado) | Corrección Implementada en el Proyecto | Archivo donde se evidencia el Fix |
|---|---|---|---|---|
| 1 | **Credenciales / IAM** | Riesgo de hardcodear `AWS_ACCESS_KEY_ID` y `AWS_SECRET_ACCESS_KEY` en variables de Docker o código Python para publicar en SNS/SQS. | Se eliminó cualquier credencial estática. La instancia EC2 usa **`IamInstanceProfile: LabInstanceProfile`** y `boto3` toma credenciales temporales del servicio de metadatos de EC2. | [`iac/main.yaml`](../iac/main.yaml) y [`app/src/app.py`](../app/src/app.py) |
| 2 | **Secretos de Aplicación e IA** | El token del periodista (`JOURNALIST_TOKEN`) y la llave `OPENROUTER_API_KEY` podrían quedar expuestos en GitHub si se escriben en el código. | Se creó `.gitignore` bloqueando `.env`, se dejó `.env.example` como plantilla limpia y en CloudFormation se usa **`NoEcho: true`** en `JournalistToken` y `OpenRouterApiKey` hacia `/etc/gtn-app.env` (`chmod 640`). | [`.gitignore`](../../.gitignore) y [`iac/main.yaml`](../iac/main.yaml) |
| 3 | **Encriptación en Reposo** | El bucket S3 inicial de la plantilla no tenía cifrado por defecto activado ni las colas SQS cifraban los eventos almacenados. | Se añadió `BucketEncryption` con **`SSEAlgorithm: AES256`** en `BucketDatos` y **`SqsManagedSseEnabled: true`** tanto en `ColaCanalVivo` como en `ColaCanalResumen`. | [`iac/main.yaml`](../iac/main.yaml) |
| 4 | **Seguridad en Contenedores** | El `Dockerfile` de la plantilla ejecutaba el proceso de Python como `root` dentro del contenedor. | Se creó el usuario sin privilegios **`appuser`** (`useradd -m appuser && USER appuser`) antes del `CMD` de Gunicorn. | [`app/Dockerfile`](../app/Dockerfile) |
| 5 | **Superficie de Red (Security Groups)** | Exponer el puerto `6379` de Redis a `0.0.0.0/0` permitiría inyección de eventos falsos en el partido. | `SecurityGroupApp` solo abre `80`, `8000`, `8001`, `8080` y `22` al exterior; `SecurityGroupRedis` restringe el puerto `6379` exclusivamente a instancias que pertenezcan a `SecurityGroupApp` (`SourceSecurityGroupId`). | [`iac/main.yaml`](../iac/main.yaml) |
| 6 | **Política de Cola SQS (Mínimo Privilegio)** | Una política SQS abierta permitiría que cualquier cuenta publicara mensajes en las colas del partido. | `PoliticaColasSnsFanOut` restringe `sqs:SendMessage` únicamente al servicio `sns.amazonaws.com` con condición estricta **`ArnEquals: aws:SourceArn: !Ref TopicEventosPartido`**. | [`iac/main.yaml`](../iac/main.yaml) |

- **Captura de referencia:** `evidencias/lab06-iam-audit.png`.
