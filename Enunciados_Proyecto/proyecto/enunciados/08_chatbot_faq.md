# 08 · Chatbot de preguntas frecuentes académicas
## 📖 El caso
Las mismas 50 preguntas llegan cada semestre al asistente del programa: fechas, requisitos, calendario. Quieren un chat en la web del programa que responda 24/7 con IA a partir de su propia base de preguntas/respuestas, con gasto acotado y controlado.
## 👥 Actores
Estudiante aspirante (pregunta) · Asistente del programa (cura las FAQ) · Director (paga la cuenta)
## 📝 Historias de usuario (épicas iniciales)
- **[HU-01]** Como aspirante, quiero preguntar en lenguaje natural y recibir respuesta útil, para no esperar días un correo.
- **[HU-02]** Como asistente, quiero mantener la base de FAQ sin programar, para que el bot no desinforme.
- **[HU-03]** Como director, quiero un tope de gasto mensual del modelo, para no sorpresas en la factura.
- **[HU-04]** Como asistente, quiero ver qué preguntas no supo responder, para mejorar la base.
## ☁️ Requisitos cloud
Lambda o ECS (API) · Bedrock (o modelo en contenedor para la demo) · DynamoDB (FAQ) · **CloudFormation**
## ⚠️ Restricciones
Prompt + contexto documentados · límite de gasto configurado · **presupuesto objetivo ≤ 10 USD/mes**
## ✅ Entregables clave
Chat web con historial · 3 respuestas buenas y 1 fallida con mejora · costo por consulta
## 🚀 Reto extra
Evaluación automática de calidad en el pipeline.
