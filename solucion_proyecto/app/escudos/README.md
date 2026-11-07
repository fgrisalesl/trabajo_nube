# 🛡️ Bodega de Escudos de Equipos (`solucion_proyecto/app/escudos/`)

Coloca en esta carpeta los escudos de los equipos en formato **`.png`**, **`.webp`**, **`.jpg`** o **`.svg`**.

## 1. ¿Cómo nombrar los archivos?
Simplemente ponles el nombre del equipo (no importan mayúsculas, espacios ni guiones bajos). Ejemplos:
- `real_madrid.png` (o `Real Madrid.png`)
- `bayern_munich.png` (o `bayern.png`)
- `manchester_city.png`
- `leipzig.png` (o `rb_leipzig.png`)
- `liverpool.png`
- `chelsea.png`
- `barcelona.png`

El sistema hace **búsqueda inteligente sin tildes ni mayúsculas**: si el partido dice `"Bayern Múnich"` o `"Bayern M."`, encontrará automáticamente `bayern.png` o `bayern_munich.png`.

## 2. Escudo por defecto (`default`)
Si juega un equipo que **no está** en esta carpeta (o cuando el tablero está en `Equipo Local vs Equipo Visitante`), el sistema busca automáticamente:
1. `default.png`
2. `default.webp`
3. `default.jpg`
4. `default.svg` (incluido por defecto)

Si quieres cambiar el escudo genérico por el tuyo propio, solo guarda tu imagen como **`default.png`** en esta carpeta y tendrá prioridad inmediata.
