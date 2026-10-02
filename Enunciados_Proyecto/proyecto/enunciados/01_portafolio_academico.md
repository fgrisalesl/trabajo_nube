# 01 · Portafolio académico del programa
## 📖 El caso
La dirección del programa quiere mostrar en un sitio público los mejores proyectos de los estudiantes. Hoy todo vive en un Drive desordenado y en época de entregas el sitio actual (un WordPress viejo) se cae con los picos de visitas. El presupuesto es casi cero y no hay personal para administrar servidores.
## 👥 Actores
Directora del programa (publica contenido) · Estudiante visitante · Egresado interesado
## 📝 Historias de usuario (épicas iniciales)
- **[HU-01]** Como directora, quiero publicar un proyecto con fotos y descripción sin ayuda técnica, para mantener el sitio vivo.
- **[HU-02]** Como visitante, quiero cargar cualquier página en menos de 2 segundos desde cualquier ciudad, para no abandonar el sitio.
- **[HU-03]** Como directora, quiero que cada cambio quede versionado y publicarse solo al aprobarse, para evitar errores en producción.
- **[HU-04]** Como directora, quiero ver cuántas visitas recibe cada proyecto, para decidir qué promover.
*(Su equipo prioriza, descompone y convierte estas historias en issues de su backlog; pueden proponer las que falten.)*
## ☁️ Requisitos cloud
S3 (hosting) · CloudFront (CDN) · ACM (HTTPS) · pipeline Jenkins (deploy) · **CloudFormation para todo el entorno**
## ⚠️ Restricciones
Sin servidores administrados (0 EC2) · **presupuesto objetivo ≤ 3 USD/mes**
## ✅ Entregables clave
URL pública con HTTPS · pipeline Jenkins que publica en cada cambio · informe de costos real vs objetivo
## 🚀 Reto extra
Ambientes staging/producción con el mismo template y parámetros distintos.
