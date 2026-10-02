# Lab 04 — Pipeline de despliegue con Jenkins
**Objetivo:** que cada cambio de código se despliegue solo (hito de la semana 11).
**Flujo (5 pasos clásicos):** clonar el código del repositorio → subir a su repo Git propio → correr con `docker compose` → configurar Jenkins para despliegue automático → verificar acceso por el puerto 80.
**Pasos:**
1. Instalar y configurar **Jenkins sobre la instancia EC2 del proyecto** (descargar → instalar → configurar).
2. Crear el job de Jenkins: al recibir un cambio, **construye la imagen Docker** del proyecto (Lab 03) y la **despliega automáticamente** sobre la instancia (puede guiarse del `Jenkinsfile` de la plantilla).
3. Provocar un cambio de código y verificar que Jenkins lo despliega **sin intervención manual**, con acceso verificado por el **puerto 80**.
**Evidencia:** configuración del job + captura de una ejecución exitosa (antes manual vs después automático).
