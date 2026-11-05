# 📋 Backlog de Historias de Usuario e Hitos Semanales — Proyecto 06

Este documento descompone las **4 épicas iniciales + el Reto Extra** del **Enunciado 06 (Minuto a minuto de torneos deportivos)** en historias de usuario listas para abrir como Issues en GitHub con la plantilla `.github/ISSUE_TEMPLATE/historia-usuario.md`.

---

## 🗂️ Historias de Usuario (Formato Dado / Cuando / Entonces)

### 🟢 `[HU-01]` Publicación rápida de eventos desde el celular del periodista
- **Historia:** Como **periodista en cancha**, quiero **reportar un gol, tarjeta o cambio desde el celular en un solo toque**, para **actualizar el marcador y el minuto a minuto en menos de 1 segundo sin saturar el grupo de WhatsApp**.
- **Criterios de aceptación:**
  - [x] **Dado** que el periodista tiene su token válido (`X-Journalist-Token`), **cuando** envía un `POST /api/events` con un GOL o TARJETA, **entonces** el sistema actualiza el marcador en Redis y publica el evento en el Topic SNS en `< 50 ms` devolviendo HTTP `201`.
  - [x] **Dado** un usuario no autenticado sin token válido, **cuando** intenta publicar en `POST /api/events`, **entonces** la API rechaza la petición con HTTP `401 Unauthorized`.
- **Hito al que pertenece:** Semana 6–7 (Servicio en línea).
- **Cómo se demostrará:** Cabina del Periodista en la interfaz web + comando `curl -X POST /api/events`.

---

### 🟢 `[HU-02]` Streaming de eventos en vivo sin recargar la página (Zero-Reload SSE)
- **Historia:** Como **aficionado en la tribuna**, quiero **ver los eventos del partido en vivo automáticamente sin recargar la página**, para **seguir cada jugada en tiempo real ahorrando batería y datos móviles**.
- **Criterios de aceptación:**
  - [x] **Dado** que el aficionado tiene abierta la página del partido, **cuando** el navegador se conecta a `GET /api/stream/vivo` (Server-Sent Events), **entonces** recibe cada nuevo evento y el cambio de marcador en `< 200 ms` sin recargar el DOM.
  - [x] **Dado** que la conexión pasa por Nginx o un balanceador en la nube, **cuando** transcurren 15 segundos sin goles, **entonces** el servidor emite un evento `heartbeat` para mantener vivo el socket TCP.
- **Hito al que pertenece:** Semana 6–7 (Servicio en línea) y Semana 9–10 (Arquitectura Fan-Out).
- **Cómo se demostrará:** Dos pestañas abiertas simultáneamente (Periodista vs. Aficionado) mostrando la actualización instantánea sin F5.

---

### 🟢 `[HU-03]` Resumen instantáneo en caché para aficionados que entran tarde
- **Historia:** Como **aficionado que entra tarde a la transmisión**, quiero **ver de inmediato el resumen consolidado de goles, tarjetas y marcador actual**, para **ponerme al día rápido en segundos**.
- **Criterios de aceptación:**
  - [x] **Dado** que el partido va en el minuto 78, **cuando** un aficionado entra tarde y consulta `GET /api/summary`, **entonces** el sistema responde desde la caché en memoria (`ElastiCache / Redis`) en `< 10 ms` con el marcador, estadísticas agregadas y lista de jugadas determinantes (`highlights`).
  - [x] **Dado** que el aficionado activa el botón **"📋 Canal RESUMEN (Llegué tarde)"**, **cuando** se visualiza el timeline, **entonces** solo se muestran las jugadas clave sin ruido de comentarios menores.
- **Hito al que pertenece:** Semana 9–10 (Arquitectura).
- **Cómo se demostrará:** Endpoint `GET /api/summary` devolviendo `"cache_hit": true` y latencia en milisegundos + botón de modo Resumen en la UI.

---

### 🟢 `[HU-04]` Soporte de pico de 1,000 lectores simultáneos en la Gran Final
- **Historia:** Como **organizador de la liga universitaria**, quiero **que el sistema aguante al menos 1,000 lectores simultáneos durante la final con un costo ≤ 15 USD/mes**, para **evitar que la plataforma colapse en los penales o goles decisivos**.
- **Criterios de aceptación:**
  - [x] **Dado** el simulador de carga (`app/simulator/load_simulator.py`), **cuando** se lanzan `1,000` lectores concurrentes mientras el periodista publica eventos, **entonces** el `100%` de las peticiones responde HTTP `200` con una latencia **p95 < 200 ms**.
  - [x] **Dado** el monitoreo de la plataforma (`GET /api/metrics`), **cuando** ocurre el pico, **entonces** se registran los percentiles `p50`, `p95` y `p99` y el conteo de entregas Fan-Out.
- **Hito al que pertenece:** Semana 11–12 (Automatización) y Semana 16 (Sustentación).
- **Cómo se demostrará:** Ejecución en vivo de `python3 app/simulator/load_simulator.py --readers 1000` y botón **"⚡ Simular Ráfaga de Final"** en el dashboard.

---

### 🌟 `[HU-05]` (Reto Extra) Priorización diferenciada entre Canal "Vivo" y Canal "Resumen"
- **Historia:** Como **arquitecto cloud de la liga**, quiero **separar el tráfico en un canal "vivo" de alta prioridad y un canal "resumen" de prioridad diferenciada**, para **garantizar entrega sub-segundo en jugadas críticas y filtrar el ruido para conexiones lentas**.
- **Criterios de aceptación:**
  - [x] **Dado** el tópico `TopicEventosPartido` en AWS SNS (`iac/main.yaml`), **cuando** se publica un evento, **entonces** `ColaCanalVivo` recibe el 100% de los mensajes con prioridad inmediata y `ColaCanalResumen` aplica una `FilterPolicy` que solo deja pasar eventos con `priority = HIGH`.
  - [x] **Dado** el backend SSE, **cuando** un cliente se suscribe a `/api/stream/vivo` vs `/api/stream/resumen`, **entonces** cada canal opera con colas y frecuencias de despacho independientes.
- **Hito al que pertenece:** Semana 9–10 (Arquitectura — Reto Extra).
- **Cómo se demostrará:** Revisión de `SuscripcionResumen` en `iac/main.yaml` + prueba en vivo publicando un `COMMENT` (solo aparece en Canal Vivo) vs un `GOAL` (aparece en Vivo y en Resumen).
