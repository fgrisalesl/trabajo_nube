# Lab 04 — Pipeline de Despliegue Automatizado con Jenkins

## 🎯 Objetivo
Lograr que cada cambio de código o infraestructura pase por validación automática (`cfn-lint`), construya la imagen Docker, despliegue la aplicación en el puerto 80/8000 y ejecute una prueba de humo y carga sin intervención manual.

## ⚙️ Etapas de nuestro [`Jenkinsfile`](../Jenkinsfile)

1. **`1. Validar IaC (CloudFormation)`**: Instala y ejecuta `cfn-lint iac/*.yaml` para garantizar que ninguna plantilla CloudFormation con errores sintácticos o de tipos llegue a AWS.
2. **`2. Auditoria Seguridad y Sintaxis`**: Compila y verifica todos los módulos Python (`app.py`, `sqs_worker.py`, `load_simulator.py`).
3. **`3. Construir Imagen Docker`**: Ejecuta `docker build -t gtn-app:latest app/`.
4. **`4. Desplegar Stack (Docker Compose / Swarm)`**: Detecta automáticamente si el nodo tiene **Docker Swarm** activo (`docker stack deploy -c docker-stack.swarm.yml gtn_sports`) o levanta el entorno con `docker compose up -d --build` exponiendo el servicio por el **puerto 80** (Nginx Gateway) y **8000** (API).
5. **`5. Smoke Test y Prueba de Pico (HU-04)`**: Verifica `curl -fsS http://localhost:8000/health` y dispara el simulador de carga para certificar la latencia bajo pico en cada release.

- **Servidor Jenkins desplegable automáticamente en la EC2 del proyecto:** [`iac/main.yaml`](../iac/main.yaml).
- **Captura de referencia:** `evidencias/lab04-jenkins-pipeline.png`.
