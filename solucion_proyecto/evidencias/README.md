# 🧪 Evidencias de Laboratorios (Nota 5 · 20%) e Hitos Semanales

En este directorio se consolidan las evidencias verificables de los **6 laboratorios del curso** aplicadas directamente a nuestro **Proyecto 06: Minuto a minuto de torneos deportivos**:

| Archivo | Laboratorio | Estado | Evidencia documentada |
|---|---|---|---|
| [lab01.md](./lab01.md) | **Lab 01 — Consola AWS y calculadora de costos** | ✅ Completo | Tabla de servicios del proyecto (`EC2`, `SNS`, `SQS`, `ElastiCache/Redis`, `S3`), configuración y costo mensual estimado (**$8.43 USD/mes** vs. presupuesto objetivo **≤ $15.00 USD/mes**). |
| [lab02.md](./lab02.md) | **Lab 02 — Servidor propio: EC2 + puertos** | ✅ Completo | Instancia EC2 desplegada, justificación de principio de mínimo privilegio en Security Group (`80`, `8000`, `22`) y prueba de servicio HTTP. |
| [lab03.md](./lab03.md) | **Lab 03 — La app viaja en contenedor** | ✅ Completo | `Dockerfile` multi-etapa con usuario no-root (`appuser`), `HEALTHCHECK` y ejecución en contenedor sobre EC2 con Docker Compose y Docker Swarm. |
| [lab04.md](./lab04.md) | **Lab 04 — Pipeline de despliegue con Jenkins** | ✅ Completo | `Jenkinsfile` automatizado con 5 etapas (`cfn-lint`, compilación, `docker build`, despliegue en puerto 80 y prueba de pico de 1,000 lectores). |
| [lab05.md](./lab05.md) | **Lab 05 — Todo el entorno en CloudFormation** | ✅ Completo | Validación `cfn-lint` sin errores, despliegue reproducible con `aws cloudformation deploy` y medición de tiempos de creación/destrucción. |
| [lab06.md](./lab06.md) | **Lab 06 — Auditoría de seguridad del proyecto** | ✅ Completo | Matriz de hallazgos → correcciones (IAM Role `LabInstanceProfile`, S3 `AES256`, SQS `SSE`, contenedor sin root, puertos restringidos y secretos en `/etc/gtn-app.env`). |

> 📸 **Nota para capturas:** Al ejecutar cada paso en sus cuentas de AWS Academy, guarden las capturas PNG en esta misma carpeta con los nombres indicados en cada archivo (`lab01-pricing-calculator.png`, `lab02-ec2-sg.png`, `lab03-docker-ps.png`, `lab04-jenkins-pipeline.png`, `lab05-stack-create.png`, `lab06-iam-audit.png`).
