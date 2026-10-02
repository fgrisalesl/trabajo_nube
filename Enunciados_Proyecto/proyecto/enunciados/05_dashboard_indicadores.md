# 05 · Dashboard de indicadores estudiantiles
## 📖 El caso
Coordinación toma decisiones con reportes manuales que nadie lee: los datos de deserción, promedios y uso de laboratorios viven en CSV dispersos por correo. Quieren un tablero actualizado que responda preguntas concretas y que cualquier asistente pueda mantener sin programar.
## 👥 Actores
Coordinador (decide) · Asistente (alimenta datos) · Comité (consume el tablero)
## 📝 Historias de usuario (épicas iniciales)
- **[HU-01]** Como asistente, quiero subir el CSV del periodo y que todo se actualice solo, para no armar reportes a mano.
- **[HU-02]** Como coordinador, quiero ver evolución de deserción por semestre, para decidir dónde intervenir.
- **[HU-03]** Como coordinador, quiero comparar uso de laboratorios por franja horaria, para reorganizar la programación.
- **[HU-04]** Como comité, quiero entrar al tablero con un link y sin instalar nada, para revisarlo en reunión.
## ☁️ Requisitos cloud
S3 (data lake crudo) · Athena o Lambda (procesamiento) · QuickSight o Grafana en EC2 · **CloudFormation**
## ⚠️ Restricciones
Datos ficticios generados por script · pipeline reproducible sin pasos manuales · **presupuesto objetivo ≤ 12 USD/mes**
## ✅ Entregables clave
Dashboard con 4+ gráficas útiles · modelo de datos documentado · costo por consulta estimado
## 🚀 Reto extra
Actualización programada (EventBridge).
