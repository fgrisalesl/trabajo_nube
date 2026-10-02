# ☁️ Gestión de Tecnologías en la Nube — 2026-2

Ecosistema del curso (UNAL): proyecto del semestre, laboratorios y rúbricas. Todo el trabajo de los equipos vive en GitHub.

## 🗺️ Mapa del repositorio
| Carpeta | Qué contiene |
|---|---|
| `proyecto/` | Reglas, hitos semanales y los **8 proyectos base** (cada equipo escoge uno, sin repetir) |
|  `plantilla-equipo/` (mirror del [repo plantilla](https://github.com/cesarpalacios/gtn-plantilla-equipo)) | Repositorio plantilla que cada equipo copia con *"Use this template"* |
| `laboratorios/` | Lab 01–06 con la evidencia exigida (Nota 5) |
| `.starter/` | LocalStack para practicar **CloudFormation gratis en local** |

## 🧰 Stack del curso
- **AWS** (cuenta de AWS Academy — se abre en la semana 2)
- **Docker** (la app del proyecto viaja en contenedor)
- **AWS CloudFormation** — la infraestructura se entrega **como código (IaC)** en YAML
- **Jenkins** — servidor CI/CD del curso: construye, valida la IaC y despliega (GitHub queda para el repositorio, issues y PRs)

## 📜 Reglas de trabajo (Git)

0. Equipos de **máximo 3 integrantes**. Cada equipo, un solo proyecto.
1. Cada equipo crea su repositorio desde el [repo plantilla](https://github.com/cesarpalacios/gtn-plantilla-equipo) (*Use this template*) y lo nombra `gtn-proyecto-<nombre>`.
2. Se trabaja con **ramas + Pull Requests**: nada se sube directo a `main` sin PR.
3. Cada **hito semanal** se entrega cerrando su issue correspondiente (plantilla en `.github/ISSUE_TEMPLATE`).
4. **Jenkins** construye y despliega en cada cambio: el pipeline (ver `Jenkinsfile`) valida la IaC con `cfn-lint`, construye la imagen Docker y la despliega en la instancia del proyecto.
5. El **README del equipo es la carta de presentación**: ficha del caso, arquitectura, costo mensual y URL de la demo.
