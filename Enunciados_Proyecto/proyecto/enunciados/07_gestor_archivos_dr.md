# 07 · Gestor de archivos con recuperación ante desastres
## 📖 El caso
La oficina de bienestar guarda documentos sensibles en un servidor físico del sótano: sin respaldo externo, sin versión histórica y con la amenaza real de falla de disco o robo. Necesitan un almacén en la nube con copia en otra región, ciclo de vida por antigüedad y la certeza de poder recuperar todo si el sótano desaparece.
## 👥 Actores
Asistente de bienestar (sube documentos) · Auditor (revisa políticas) · Director (responde por los datos)
## 📝 Historias de usuario (épicas iniciales)
- **[HU-01]** Como asistente, quiero subir un documento clasificado y consultarlo después, para dejar el papel.
- **[HU-02]** Como director, quiero que todo viva en dos regiones distintas, para sobrevivir a un desastre regional.
- **[HU-03]** Como director, quiero versiones históricas ante borrados accidentales, para revertir errores.
- **[HU-04]** Como auditor, quiero que los archivos de más de 2 años se archiven baratos solos, para bajar costos.
- **[HU-05]** Como director, quiero probar que la copia realmente sirve, para confiar en el plan.
## ☁️ Requisitos cloud
S3 (versionado + replication cross-region) · lifecycle a Glacier · IAM mínimo necesario · **CloudFormation**
## ⚠️ Restricciones
**Presupuesto objetivo ≤ 8 USD/mes** · política de retención documentada · simulación de pérdida de región primaria
## ✅ Entregables clave
Subida/descarga funcionando · demostración de failover · tabla de costos por GB y por recuperación
## 🚀 Reto extra
Notificación (S3→SNS/Lambda) por cada archivo crítico subido.
