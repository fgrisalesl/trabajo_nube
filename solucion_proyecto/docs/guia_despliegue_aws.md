# Guía Paso a Paso: Cómo Subir y Desplegar el Proyecto en AWS Academy

Esta guía detalla paso a paso cómo subir el proyecto actual a tu laboratorio de **AWS Academy** y cómo cualquier persona (el profesor, tus compañeros o tú desde el celular) puede abrirlo desde su navegador en internet.

---

## ¿El proyecto así como está ahora se puede subir a AWS?

**Sí, 100%.** Ya dejé sincronizados todos los archivos de despliegue para que incluyan todos los cambios nuevos:
- **[Dockerfile](file:///home/felipe/Documentos/PROYECTOS/trabajo_nube/solucion_proyecto/app/Dockerfile):** Incluye `ffmpeg` (para extraer el audio de los videos `.mp4`), copia automáticamente tu bodega de 377 escudos (`app/escudos/`) y tu bodega de íconos (`app/iconos/`).
- **[docker-compose.yml](file:///home/felipe/Documentos/PROYECTOS/trabajo_nube/solucion_proyecto/app/docker-compose.yml):** Levanta Redis, el Portal de Aficionados (`puerto 8000`), la Consola del Periodista (`puerto 8001`), el Worker SQS y el Gateway Nginx (`puerto 80`) inyectando `GROQ_API_KEY` y montando `media/`, `escudos/` e `iconos/`.
- **[iac/main.yaml](file:///home/felipe/Documentos/PROYECTOS/trabajo_nube/solucion_proyecto/iac/main.yaml):** Crea toda la infraestructura en **1 sola cuenta de AWS Academy** (VPC, SNS, 2 Colas SQS, S3 y la instancia EC2 con los puertos `80`, `8000`, `8001` y `8080` abiertos al público y el parámetro `GroqApiKey` configurado en `/etc/gtn-app.env`).

> **Importante sobre los videos `.mp4` y el archivo `.env`:**  
> Por buenas prácticas de Git y seguridad (`.gitignore`), ni tu archivo `.env` (donde está tu API Key de Groq) ni los videos `.mp4` pesados de `app/media/` se suben a GitHub. En el **Paso 2** de abajo verás cómo pasarle tu `GroqApiKey` directamente al comando de CloudFormation y cómo subir tus videos desde la propia página web de la Cabina del Periodista una vez desplegada.

---

## Paso 1: Subir tu código a tu repositorio de GitHub (Desde tu PC)

Los archivos que deben quedar en la **raíz** de tu repositorio de GitHub son los que están dentro de `solucion_proyecto/` (`app/`, `iac/`, `docs/`, `evidencias/`, `Jenkinsfile`, `README.md`).

Abre una terminal en tu computador dentro de la carpeta `solucion_proyecto/` y ejecuta:

```bash
cd /home/felipe/Documentos/PROYECTOS/trabajo_nube/solucion_proyecto

git init
git branch -M main
git add .
git commit -m "feat: plataforma UNAL Sports completa con Groq Whisper v3 Turbo, FotMob UI y CloudFormation"

# Reemplaza la URL por la de tu repositorio en GitHub:
git remote add origin https://github.com/<TU_USUARIO>/<TU_REPO>.git
git push -u origin main
```
*(Nota: Tus 377 escudos `.svg` de `app/escudos/` y tus íconos de `app/iconos/` sí se suben a GitHub porque pesan muy poco y así quedan listos en AWS automáticamente).*

---

## Paso 2: Crear toda la infraestructura en AWS Academy (En la Nube)

1. Entra a tu cuenta de **AWS Academy Learner Lab** y haz clic en **Start Lab**.
2. Espera a que el punto al lado de *AWS* se ponga **Verde** y haz clic en **AWS** para abrir la consola de administración.
3. En la barra superior derecha de la consola de AWS, haz clic en el ícono de terminal **`>_` (AWS CloudShell)**.
4. Cuando cargue la terminal de CloudShell, clona tu repositorio de GitHub y despliega la plantilla de CloudFormation con tu llave de Groq:

```bash
# 1. Clonar tu repositorio en CloudShell
git clone https://github.com/<TU_USUARIO>/<TU_REPO>.git
cd <TU_REPO>

# 2. Desplegar toda la infraestructura con CloudFormation (tarda ~2 minutos)
aws cloudformation deploy \
  --template-file iac/main.yaml \
  --stack-name gtn-unal-sports \
  --capabilities CAPABILITY_NAMED_IAM \
  --parameter-overrides \
    NombreEquipo=unal-sports \
    Ambiente=lab \
    ProyectoId=proyecto-06 \
    InstanceType=t3.small \
    GroqApiKey=<TU_GROQ_API_KEY>
```

5. Apenas termine el comando, ejecuta este comando en el mismo CloudShell para ver la **IP pública y las URLs** de tu servidor:

```bash
aws cloudformation describe-stacks \
  --stack-name gtn-unal-sports \
  --query "Stacks[0].Outputs" \
  --output table
```
Guarda el valor de **`EC2PublicIP`** (por ejemplo `54.160.XX.XX`) o **`DemoURL`**.

---

## Paso 3: Levantar los Contenedores en la Instancia EC2

Cuando CloudFormation crea la instancia EC2, su script `UserData` instala automáticamente **Docker, Docker Compose, Git, Java 17 y Jenkins**, y guarda tu `GROQ_API_KEY`, el `SNS_TOPIC_ARN` y las URLs de las colas `SQS` en el archivo `/etc/gtn-app.env`.

Tienes **dos formas** de levantar la aplicación dentro de la EC2 (puedes usar la Opción A para dejarla corriendo en 1 minuto, o la Opción B con Jenkins para mostrar el pipeline CI/CD):

### Opción A — Directo por terminal de EC2 (La más rápida, en 1 minuto)
1. En la consola de AWS ve a **EC2 → Instances**.
2. Selecciona la instancia **`gtn-unal-sports-ec2-server`** y haz clic arriba en **Connect → Connect** (usando *EC2 Instance Connect* desde el navegador).
3. Espera ~2 minutos si la instancia acaba de crearse para que termine el `UserData` (puedes verificar con `docker --version`).
4. Ejecuta estos comandos en la terminal de la EC2:

```bash
git clone https://github.com/<TU_USUARIO>/<TU_REPO>.git
cd <TU_REPO>/app

# Copiar las variables de entorno generadas por CloudFormation (SNS, SQS y GROQ_API_KEY)
sudo cp /etc/gtn-app.env .env
sudo chown ec2-user:ec2-user .env

# Construir y levantar todos los microservicios en segundo plano
sg docker -c "docker compose up -d --build"
```

5. Verifica que los 5 contenedores estén arriba (`Up`):
```bash
sg docker -c "docker compose ps"
```

---

### Opción B — Desplegar automáticamente desde Jenkins CI/CD (Puerto 8080)
Si quieres mostrarle al profesor cómo **Jenkins** despliega todo automáticamente desde GitHub:
1. En la terminal de la EC2, obtén la contraseña inicial de Jenkins:
   ```bash
   sudo cat /var/lib/jenkins/secrets/initialAdminPassword
   ```
2. Abre en tu navegador: `http://<EC2_PUBLIC_IP>:8080`
3. Pega la contraseña, haz clic en **"Install suggested plugins"** y crea tu usuario.
4. Haz clic en **New Item**, ponle `gtn-unal-sports-pipeline`, selecciona **Pipeline** y dale **OK**.
5. En la sección **Pipeline**:
   - **Definition:** `Pipeline script from SCM`
   - **SCM:** `Git`
   - **Repository URL:** `https://github.com/<TU_USUARIO>/<TU_REPO>.git`
   - **Branch Specifier:** `*/main`
   - **Script Path:** `Jenkinsfile`
6. Haz clic en **Save** y luego en **Build Now**. Jenkins validará `iac/main.yaml`, construirá la imagen Docker y levantará todos los contenedores usando `/etc/gtn-app.env`.

---

## Paso 4: ¿Cómo puede verlo cualquier persona desde su navegador o celular?

Como el `SecurityGroupApp` de tu plantilla CloudFormation abre los puertos `80`, `8000`, `8001` y `8080` hacia internet (`0.0.0.0/0`), **cualquier persona en cualquier red Wi-Fi o datos móviles** puede entrar desde su navegador usando la IP pública de tu EC2 (`<EC2_PUBLIC_IP>`):

| Quién entra | Qué URL debe abrir en su navegador | Qué verá |
| :--- | :--- | :--- |
| **Cualquier Espectador / Profesor / Compañeros** | **`http://<EC2_PUBLIC_IP>`** *(o `http://<EC2_PUBLIC_IP>:8000`)* | **Portal Público de Aficionados (Estilo FotMob):** Marcador en vivo, escudos de clubes/selecciones, estadísticas y cronología minuto a minuto que se actualiza sola sin recargar la página. |
| **Tú (Periodista / Cabina de Transmisión)** | **`http://<EC2_PUBLIC_IP>:8001`** *(o `http://<EC2_PUBLIC_IP>/periodista`)* | **Consola de Prensa:** Donde subes y reproduces el video `.mp4` del partido (usando el botón **"Subir Video / Audio"**), narras por micrófono, publicas jugadas manuales o activas el **Simulador de 1,000 Lectores Concurrentes**. |
| **Evaluador CI/CD** | **`http://<EC2_PUBLIC_IP>:8080`** | **Servidor Jenkins CI/CD** con el pipeline de validación y despliegue. |

### Cómo subir tus videos de resumen una vez esté en AWS:
1. Entra desde tu navegador a `http://<EC2_PUBLIC_IP>:8001`.
2. En el **Modo 1**, haz clic en el botón **"Subir Video / Audio"** y selecciona tu video `.mp4` (por ejemplo `Bayern M. 4-3 Real Madrid.mp4` o `Manchester_CIty_Vs_Leipzig.mp4`).
3. El video quedará guardado directamente en el servidor EC2 y al darle **Play** empezará a transmitir las jugadas y actualizar el marcador en los celulares y navegadores de todas las personas que estén viendo `http://<EC2_PUBLIC_IP>`.
