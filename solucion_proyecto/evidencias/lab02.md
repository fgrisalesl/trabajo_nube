# Lab 02 — Servidor propio: EC2 + Puertos (Security Group)

## 🎯 Objetivo
Levantar el servidor EC2 del proyecto y configurar su **Security Group** bajo el principio de mínimo privilegio.

## 🔒 ¿Por qué nuestro Security Group (`SecurityGroupApp`) solo abre lo estrictamente necesario?

En `iac/main.yaml` definimos las reglas de entrada (`SecurityGroupIngress`) únicamente para los puertos requeridos por la operación del servicio:

| Puerto | Protocolo | Origen (`CIDR`) | Justificación Técnica y de Seguridad |
|---|---|---|---|
| **`80`** | TCP | `0.0.0.0/0` | Tráfico HTTP público hacia el **Nginx API Gateway** que sirve el Portal de Aficionados y el streaming **Server-Sent Events (SSE)** sin buffering. |
| **`8000`** | TCP | `0.0.0.0/0` | Microservicio 1 (`fan-portal` — CQRS Read) para validación de `/health` y pruebas de carga del simulador. |
| **`8001`** | TCP | `0.0.0.0/0` | Microservicio 2 (`journalist-studio` — CQRS Write): App independiente exclusiva para la **Cabina del Periodista (`HU-01`)**. |
| **`8080`** | TCP | `0.0.0.0/0` | Interfaz web del servidor **Jenkins CI/CD** instalado sobre la misma instancia EC2 del proyecto (Lab 04). |
| **`22`** | TCP | `!Ref AllowedSshCidr` | Administración remota por SSH. |

### Puertos explícitamente bloqueados hacia Internet:
- **Puerto `6379` (Redis):** No está expuesto en el Security Group público. Redis solo acepta conexiones dentro de la red puente/overlay de Docker o desde el Security Group interno `SecurityGroupRedis`, impidiendo accesos no autorizados a la caché del partido.

- **Captura de referencia:** `evidencias/lab02-ec2-sg.png`.
