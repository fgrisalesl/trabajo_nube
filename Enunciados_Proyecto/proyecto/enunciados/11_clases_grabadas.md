# 11 · Plataforma de clases grabadas
## 📖 El caso
Las clases se graban en videos pesados que se comparten por enlaces temporales: nadie encuentra nada, los enlaces expiran y consumirlos en celular se come los datos. La facultad quiere una plataforma propia donde el video suba una vez y se sirva optimizado a cualquier dispositivo.
## 👥 Actores
Docente (sube la grabación) · Estudiante (ve la clase) · Administrador de plataforma
## 📝 Historias de usuario (épicas iniciales)
- **[HU-01]** Como docente, quiero subir el video de mi clase con título y materia, para que quede disponible.
- **[HU-02]** Como estudiante, quiero ver el video fluido en mi celular, para repasar donde sea.
- **[HU-03]** Como estudiante, quiero buscar clases por materia y fecha, para encontrar rápido.
- **[HU-04]** Como administrador, quiero que el almacenamiento viejo se archive barato solo, para controlar costos.
- **[HU-05]** Como docente, quiero que solo mis estudiantes accedan, para cuidar el contenido.
## ☁️ Requisitos cloud
S3 (videos + versiones optimizadas) · CloudFront (streaming) · Lambda (procesamiento al subir) · **CloudFormation**
## ⚠️ Restricciones
Procesamiento al subir (formatos/clips demostrables) · acceso restringido · **presupuesto objetivo ≤ 15 USD/mes**
## ✅ Entregables clave
Subida → procesamiento → reproducción end-to-end · búsqueda funcional · política de ciclo de vida documentada
## 🚀 Reto extra
URLs firmadas con expiración para el acceso.
