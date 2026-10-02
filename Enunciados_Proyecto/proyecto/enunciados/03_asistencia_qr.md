# 03 · Sistema de asistencia con QR (serverless)
## 📖 El caso
Controlar asistencia a laboratorios consume 10 minutos de cada sesión en llamado a lista. La coordinación quiere que el estudiante escanee un QR único por sesión y la asistencia quede registrada al instante con reporte automático. No quieren servidores: las clases son 2 días a la semana y el resto del tiempo el sistema estaría desperdiciado.
## 👥 Actores
Docente (genera QR de la sesión) · Estudiante (escanea) · Coordinación (reportes)
## 📝 Historias de usuario (épicas iniciales)
- **[HU-01]** Como docente, quiero generar un QR único y efímero para cada sesión, para evitar que escaneen desde la casa.
- **[HU-02]** Como estudiante, quiero escanear y ver confirmación inmediata, para saber que quedé registrado.
- **[HU-03]** Como coordinación, quiero un reporte automático por curso y fecha, para detectar deserción a tiempo.
- **[HU-04]** Como coordinación, quiero que el costo sea proporcional al uso, para no pagar servidores ociosos.
## ☁️ Requisitos cloud
API Gateway · Lambda · DynamoDB · S3 (reporte) · **CloudFormation completo**
## ⚠️ Restricciones
Cero instancias EC2 · **presupuesto objetivo ≤ 1 USD/mes** · QR generado por la propia app
## ✅ Entregables clave
Endpoint de registro funcionando · reporte HTML automático · explicación de costo por solicitud
## 🚀 Reto extra
Alerta por correo (SNS) al superar límite de inasistencias.
