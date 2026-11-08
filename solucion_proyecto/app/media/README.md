# 🎬 Carpeta de Videos y Audios del Partido (`solucion_proyecto/app/media/`)

Aquí puedes colocar tus videos (`.mp4`, `.webm`) o audios (`.mp3`, `.wav`, `.ogg`, `.m4a`) con la voz real del comentarista del partido (como tu archivo `Bayern M. 4-3 Real Madrid.mp4`).

## ⚙️ ¿Cómo funciona en tiempo real?
1. Cuando seleccionas tu video en la **Cabina del Periodista (`http://localhost:8000/periodista`)** y le das **Play ▶️**:
   - El servidor extrae automáticamente los fragmentos de audio del video con **`ffmpeg`** a medida que el reloj del reproductor avanza.
   - Transcribe la voz real del comentarista del video con **Speech-to-Text (`SpeechRecognition`)**.
   - Envía esa transcripción real a **Groq Api**, que detecta qué pasó (Gol, Penal, Amarilla, Roja, Cambio o Comentario), actualiza el minuto, el marcador y publica la jugada en la pantalla de los espectadores en tiempo real.
