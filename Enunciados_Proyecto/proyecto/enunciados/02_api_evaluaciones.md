# 02 · API de evaluaciones (notas en línea)
## 📖 El caso
Los docentes registran notas en Excel y las envían por correo; en cierre de semestre el proceso genera colas y errores de versión. La facultad contrata a su equipo para construir una API que permita registrar y consultar notas por curso de forma confiable, y que aguante el pico de consultas cuando salen boletines.
## 👥 Actores
Docente (registra notas) · Estudiante (consulta) · Administrador académico
## 📝 Historias de usuario (épicas iniciales)
- **[HU-01]** Como docente, quiero registrar la nota de un actividad con su peso, para calcular la definitiva sin Excel.
- **[HU-02]** Como estudiante, quiero consultar mis notas en línea y saber mi promedio, para hacer seguimiento.
- **[HU-03]** Como administrador, quiero que los datos solo sean visibles para su dueño, para cumplir la política de datos.
- **[HU-04]** Como estudiante, quiero que las consultas sigan rápidas el día de boletines, para no esperar.
*(Los equipos descomponen estas historias en tareas técnicas: capa de datos, API, autenticación, pruebas de carga.)*
## ☁️ Requisitos cloud
EC2/ECS con ALB · RDS (MySQL/PostgreSQL) · Security Groups por capa · **CloudFormation completo**
## ⚠️ Restricciones
App en contenedor Docker · base de datos NO en el contenedor · **presupuesto objetivo ≤ 15 USD/mes** · pruebas de carga documentadas
## ✅ Entregables clave
Endpoint `/health` y CRUD de notas · esquema de BD versionado · diagrama multi-capa
## 🚀 Reto extra
Autoescalado del frente web probado con métricas de CloudWatch.
