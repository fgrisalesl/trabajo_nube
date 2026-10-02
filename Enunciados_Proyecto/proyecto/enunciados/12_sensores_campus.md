# 12 · Sensores ambientales del campus
## 📖 El caso
El campus instaló sensores de temperatura y ruido en varias salas, pero los datos se pierden en un log local. Bienestar universitario quiere entender qué salas son incómodas y en qué franjas, con alertas cuando un ambiente se vuelve crítico.
## 👥 Actores
Técnico de mantenimiento (instala sensores) · Bienestar universitario (analiza) · Comunidad (se beneficia)
## 📝 Historias de usuario (épicas iniciales)
- **[HU-01]** Como técnico, quiero registrar un sensor con su ubicación, para saber de dónde viene cada dato.
- **[HU-02]** Como bienestar, quiero ver la temperatura/ruido de cada sala en tiempo casi real, para detectar molestias.
- **[HU-03]** Como bienestar, quiero alertas cuando un valor supera el umbral, para actuar rápido.
- **[HU-04]** Como bienestar, quiero el histórico por franja horaria, para priorizar intervenciones.
- **[HU-05]** Como técnico, quiero que el sensor funcione aunque la red falle un rato, para no perder datos.
## ☁️ Requisitos cloud
API Gateway + Lambda (ingesta) · DynamoDB o Timestream (series) · CloudWatch (alarmas) · SNS (alertas) · **CloudFormation**
## ⚠️ Restricciones
Simulador de sensores incluido (script) · **presupuesto objetivo ≤ 8 USD/mes** · datos mínimos por 7 días corridos
## ✅ Entregables clave
Ingesta → dashboard → alerta demostrada · simulador versionado · diseño para escala (más sensores)
## 🚀 Reto extra
Agregación por edificio con KPI de confort.
