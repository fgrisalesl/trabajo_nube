# 09 · Reservas de laboratorios
## 📖 El caso
Los laboratorios de cómputo se reservan por un cuaderno en la puerta: hay choques de horarios, salas ocupadas con 3 estudiantes y semanas completas sin que nadie sepa la disponibilidad real. El centro de laboratorios quiere un sistema de reservas en línea con reglas claras y visibilidad total.
## 👥 Actores
Docente (reserva sala) · Estudiante (consulta disponibilidad) · Administrador de laboratorios (gestiona salas y reglas)
## 📝 Historias de usuario (épicas iniciales)
- **[HU-01]** Como docente, quiero reservar una sala en una franja horaria, para programar mi práctica sin chocar.
- **[HU-02]** Como docente, quiero cancelar o mover mi reserva, para ajustarme a cambios de clase.
- **[HU-03]** Como administrador, quiero definir capacidad y reglas por sala (p. ej. mínimo 10 estudiantes), para evitar salas desperdiciadas.
- **[HU-04]** Como estudiante, quiero ver la disponibilidad de la semana, para saber dónde puedo trabajar.
- **[HU-05]** Como administrador, quiero recibir alerta de reservas de última hora, para preparar la sala.
## ☁️ Requisitos cloud
EC2/ECS + ALB (API) · RDS (reservas) · SES o SNS (notificaciones) · **CloudFormation completo**
## ⚠️ Restricciones
App en contenedor · sin doble reserva (concurrencia demostrada) · **presupuesto objetivo ≤ 12 USD/mes**
## ✅ Entregables clave
Flujo reservar/consultar/cancelar funcionando · prueba de concurrencia (dos reservas simultáneas) · diagrama
## 🚀 Reto extra
Sugeridor de sala óptima según capacidad y franja.
