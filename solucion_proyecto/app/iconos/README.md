# Bodega de Logos e Íconos de la Interfaz (`solucion_proyecto/app/iconos/`)

En esta carpeta puedes colocar tus propios logos e íconos personalizados (`.png`, `.webp`, `.svg` o `.jpg`).
El servidor detecta automáticamente si subiste un archivo `.png` o `.webp` con cualquiera de estos nombres base y le da prioridad sobre el `.svg` incluido por defecto:

| Nombre de archivo que puedes subir | Dónde aparece en la plataforma |
| :--- | :--- |
| `logo.png` (o `logo.svg`, `logo.webp`) | Logo principal en la barra superior del Portal de Aficionados y Cabina |
| `balon.png` (o `gol.png`) | Ícono de Gol en el minuto a minuto, estadísticas y selector manual |
| `amarilla.png` | Ícono de Tarjeta Amarilla en el minuto a minuto, marcador y cabina |
| `roja.png` | Ícono de Tarjeta Roja en el minuto a minuto, marcador y cabina |
| `cambio.png` | Ícono de Sustitución / Cambio en el minuto a minuto, marcador y cabina |
| `penal.png` | Ícono de Penal / VAR en el minuto a minuto y cabina |
| `comentario.png` | Ícono de Minuto a Minuto / Relato general |
| `microfono.png` | Ícono del botón de Narrar por Micrófono en la Cabina del Periodista |

> **Nota:** No necesitas cambiar nada en el código cuando reemplaces o agregues una imagen aquí. La ruta `/api/icon/<nombre>` busca primero `.png`, luego `.webp`, luego `.jpg` y por último `.svg`.
