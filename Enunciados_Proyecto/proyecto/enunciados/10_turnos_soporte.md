# 10 · Turnos y cola de soporte TI
## 📖 El caso
La oficina de soporte TI atiende por correo: los correos se pierden, nadie sabe cuál lleva cada caso y el jefe no tiene visibilidad de tiempos. Quieren un sistema de tickets con cola, estados y métricas de atención que no requiera instalar nada a los usuarios.
## 👥 Actores
Usuario (reporta incidente) · Agente de soporte (atiende) · Jefe de soporte (mide)
## 📝 Historias de usuario (épicas iniciales)
- **[HU-01]** Como usuario, quiero crear un ticket describiendo mi problema, para no depender del correo.
- **[HU-02]** Como agente, quiero ver la cola de tickets pendientes y tomar uno, para organizar el trabajo.
- **[HU-03]** Como agente, quiero cambiar el estado del ticket (en proceso/resuelto), para que el usuario sepa.
- **[HU-04]** Como jefe, quiero ver tiempos promedio de atención y tickets por agente, para medir el servicio.
- **[HU-05]** Como usuario, quiero recibir notificación cuando mi ticket cambia de estado, para hacer seguimiento.
## ☁️ Requisitos cloud
API Gateway + Lambda o ECS · DynamoDB o RDS (tickets) · SQS (cola) · SES/SNS (notificaciones) · **CloudFormation**
## ⚠️ Restricciones
Los tickets entran por cola asincrónica · **presupuesto objetivo ≤ 10 USD/mes** · datos de prueba cargados
## ✅ Entregables clave
Alta y gestión de tickets end-to-end · dashboard simple de métricas · explicación del patrón cola
## 🚀 Reto extra
SLA: alerta al jefe si un ticket supera 24h sin atención.
