"""
UNAL Sports Live — Proyecto 06: Minuto a minuto de torneos deportivos
Arquitectura CQRS + Fan-Out + Agente de Narración IA en Tiempo Real (OpenRouter + Transcripción Real FFmpeg/STT):
  - Servicio 1 (fan-portal / modo READ): Exclusivo para los 1,000+ Aficionados (SSE + Caché O(1)). Arranca como Tablero en Blanco (0-0).
  - Servicio 2 (journalist-studio / modo WRITE): Consola del Periodista + Auto-Narrador IA en vivo desde Video/Audio/Micrófono.
"""
import io
import os
import re
import json
import time
import uuid
import socket
import subprocess
import threading
from pathlib import Path
from datetime import datetime, timezone
from collections import deque
from flask import Flask, request, jsonify, Response, render_template, stream_with_context, send_from_directory
from werkzeug.utils import secure_filename

try:
    import speech_recognition as sr
except ImportError:
    sr = None

try:
    import requests as http_requests
except ImportError:
    http_requests = None

try:
    import redis
except ImportError:
    redis = None

try:
    import boto3
except ImportError:
    boto3 = None

app = Flask(__name__)

# ==============================================================================
# CARGA DE ARCHIVO .env LOCAL (Sin exponer llaves en Git - Lab 06)
# ==============================================================================
BASE_APP_DIR = Path(__file__).resolve().parent.parent
MEDIA_DIR = BASE_APP_DIR / "media"
MEDIA_DIR.mkdir(parents=True, exist_ok=True)


def load_dotenv_file():
    env_candidates = [
        BASE_APP_DIR / ".env",
        Path("/etc/gtn-app.env")
    ]
    for env_path in env_candidates:
        if env_path.exists():
            try:
                for line in env_path.read_text(encoding="utf-8").splitlines():
                    line = line.strip()
                    if not line or line.startswith("#") or "=" not in line:
                        continue
                    k, v = line.split("=", 1)
                    k = k.strip()
                    v = v.strip().strip('"').strip("'")
                    if k and k not in os.environ:
                        os.environ[k] = v
            except Exception:
                pass


load_dotenv_file()

# ==============================================================================
# CONFIGURACIÓN Y VARIABLES DE ENTORNO
# ==============================================================================
SERVICE_ROLE = os.environ.get("SERVICE_ROLE", "all").lower()
PORT = int(os.environ.get("PORT", "8000"))
REDIS_HOST = os.environ.get("REDIS_HOST", "redis")
REDIS_PORT = int(os.environ.get("REDIS_PORT", "6379"))
AWS_REGION = os.environ.get("AWS_REGION", "us-east-1")
SNS_TOPIC_ARN = os.environ.get("SNS_TOPIC_ARN", "")
SQS_LIVE_URL = os.environ.get("SQS_LIVE_URL", "")
SQS_SUMMARY_URL = os.environ.get("SQS_SUMMARY_URL", "")
JOURNALIST_TOKEN = os.environ.get("JOURNALIST_TOKEN", "unal-periodista-2026")
OPENROUTER_API_KEY = os.environ.get("OPENROUTER_API_KEY", "")
OPENROUTER_MODEL = os.environ.get("OPENROUTER_MODEL", "openrouter/free")
HOSTNAME = socket.gethostname()

ALLOWED_MEDIA_EXT = {".mp4", ".webm", ".ogg", ".mp3", ".wav", ".m4a"}

# Conexión a Redis (ElastiCache en AWS o contenedor Redis en Docker/Swarm)
redis_client = None
if redis:
    try:
        rc = redis.Redis(host=REDIS_HOST, port=REDIS_PORT, decode_responses=True, socket_connect_timeout=2)
        rc.ping()
        redis_client = rc
    except Exception:
        redis_client = None

# Cliente AWS SNS/SQS (usa IAM Role de la instancia EC2 en AWS Academy: LabInstanceProfile)
sns_client = None
sqs_client = None
if boto3 and SNS_TOPIC_ARN:
    try:
        sns_client = boto3.client("sns", region_name=AWS_REGION)
        sqs_client = boto3.client("sqs", region_name=AWS_REGION)
    except Exception:
        pass

# ==============================================================================
# TABLERO EN BLANCO INICIAL (0 - 0, Minuto 0, 0 Eventos prefabricados)
# ==============================================================================
DEFAULT_MATCH = {
    "match_id": "LIVE-MATCH-2026",
    "tournament": "Transmisión Oficial En Vivo",
    "home_team": "Equipo Local",
    "away_team": "Equipo Visitante",
    "home_score": 0,
    "away_score": 0,
    "minute": 0,
    "status": "EN ESPERA DE INICIO",
    "updated_at": datetime.now(timezone.utc).isoformat()
}

INITIAL_EVENTS = []

local_events = deque(INITIAL_EVENTS, maxlen=200)
local_match = dict(DEFAULT_MATCH)
local_subscribers_vivo = []
local_subscribers_resumen = []
latency_samples = deque([3.8], maxlen=500)
metrics_lock = threading.Lock()
active_sse_clients = {"vivo": 0, "resumen": 0}
total_events_published = 0
total_fanout_deliveries = 0


def init_redis_seed():
    """Inicializa el tablero en blanco en Redis si aún no existe."""
    if not redis_client:
        return
    try:
        if not redis_client.exists("match:state"):
            redis_client.set("match:state", json.dumps(DEFAULT_MATCH))
        if not redis_client.exists("match:metrics:events_published"):
            redis_client.set("match:metrics:events_published", 0)
        if not redis_client.exists("match:metrics:fanout_deliveries"):
            redis_client.set("match:metrics:fanout_deliveries", 0)
    except Exception:
        pass


init_redis_seed()


# ==============================================================================
# FUNCIONES DE NEGOCIO Y PATRÓN FAN-OUT (Canal Vivo vs Canal Resumen)
# ==============================================================================
HIGH_PRIORITY_TYPES = {"GOAL", "RED_CARD", "PENALTY", "MATCH_START", "MATCH_END", "VAR"}


def classify_event_priority(event_type: str) -> tuple[str, str]:
    if event_type.upper() in HIGH_PRIORITY_TYPES:
        return "HIGH", "vivo"
    return "LOW", "resumen"


def get_match_state() -> dict:
    if redis_client:
        try:
            raw = redis_client.get("match:state")
            if raw:
                return json.loads(raw)
        except Exception:
            pass
    return dict(local_match)


def save_match_state(state: dict, clear_events: bool = False):
    global total_events_published, total_fanout_deliveries
    state["updated_at"] = datetime.now(timezone.utc).isoformat()
    local_match.update(state)
    if clear_events:
        local_events.clear()
        total_events_published = 0
        total_fanout_deliveries = 0
    if redis_client:
        try:
            pipe = redis_client.pipeline()
            pipe.set("match:state", json.dumps(state))
            if clear_events:
                pipe.delete("match:events")
                pipe.set("match:metrics:events_published", 0)
                pipe.set("match:metrics:fanout_deliveries", 0)
            payload_str = json.dumps({"match": state, "reset": clear_events})
            pipe.publish("channel:vivo", payload_str)
            pipe.publish("channel:resumen", payload_str)
            pipe.execute()
        except Exception:
            pass
    else:
        payload_str = json.dumps({"match": state, "reset": clear_events})
        for q in list(local_subscribers_vivo):
            q.append(payload_str)
        for q in list(local_subscribers_resumen):
            q.append(payload_str)


def get_all_events(limit: int = 100) -> list:
    if redis_client:
        try:
            items = redis_client.lrange("match:events", -limit, -1)
            events = [json.loads(x) for x in items]
            events.reverse()
            return events
        except Exception:
            pass
    ev_list = list(local_events)
    ev_list.reverse()
    return ev_list[:limit]


def infer_teams_from_filename(filename: str) -> tuple[str, str] | None:
    """
    Si el usuario sube un archivo como 'Bayern M. 4-3 Real Madrid.mp4' o 'Barcelona vs Real Madrid.mp4',
    detecta automáticamente los nombres de los dos equipos del archivo para configurar el tablero inicial.
    """
    stem = Path(filename).stem.strip()
    # Patrón 1: EquipoA 4-3 EquipoB  o  EquipoA vs EquipoB
    m = re.search(r"^(.+?)\s+(?:\d+\s*[-:]\s*\d+|vs\.?|contra|[-–])\s+(.+)$", stem, re.IGNORECASE)
    if m:
        t1 = m.group(1).strip(" _-.")
        t2 = m.group(2).strip(" _-.")
        if len(t1) >= 2 and len(t2) >= 2:
            return t1, t2
    return None


def publish_event_fanout(event_data: dict, simulated_readers_override: int = 0) -> dict:
    """
    Implementa el Patrón Fan-Out:
    1. Recibe la jugada (manual o interpretada por la IA desde el video/audio/micrófono).
    2. Actualiza nombres de equipos, minuto y marcador en tiempo real.
    3. Publica en AWS SNS -> 2 Colas SQS (Vivo y Resumen) -> Redis Cache O(1) -> Server-Sent Events (SSE).
    """
    global total_events_published, total_fanout_deliveries
    t0 = time.perf_counter()

    state = get_match_state()

    if event_data.get("home_team") and event_data["home_team"] not in {"Equipo Local", "Local", ""}:
        state["home_team"] = str(event_data["home_team"]).strip()
    if event_data.get("away_team") and event_data["away_team"] not in {"Equipo Visitante", "Visitante", ""}:
        state["away_team"] = str(event_data["away_team"]).strip()
    if event_data.get("tournament"):
        state["tournament"] = str(event_data["tournament"]).strip()

    ev_type = str(event_data.get("type", "COMMENT")).upper()
    if ev_type not in {"GOAL", "PENALTY", "RED_CARD", "YELLOW_CARD", "SUBSTITUTION", "COMMENT", "MATCH_START", "MATCH_END"}:
        ev_type = "COMMENT"

    priority, primary_channel = classify_event_priority(ev_type)
    raw_min = event_data.get("minute")
    minute = int(raw_min) if (raw_min is not None and str(raw_min).isdigit()) else max(1, int(state.get("minute", 0)) + 1)

    team = str(event_data.get("team", "NEUTRAL")).upper()
    if team not in {"HOME", "AWAY", "NEUTRAL"}:
        team = "NEUTRAL"

    event = {
        "id": f"evt-{uuid.uuid4().hex[:8]}",
        "minute": minute,
        "type": ev_type,
        "team": team,
        "team_name": state["home_team"] if team == "HOME" else (state["away_team"] if team == "AWAY" else "Transmisión Oficial"),
        "player": event_data.get("player") or "Relato en Vivo",
        "description": event_data.get("description") or "Jugada reportada en vivo",
        "priority": priority,
        "channel": primary_channel,
        "ai_generated": bool(event_data.get("ai_generated", False)),
        "ai_model": event_data.get("ai_model", ""),
        "timestamp": time.time(),
        "created_iso": datetime.now(timezone.utc).isoformat(),
        "node": HOSTNAME
    }

    # Actualizar estado del partido y marcador
    state["minute"] = minute
    if state.get("status") == "EN ESPERA DE INICIO" or ev_type == "MATCH_START":
        state["status"] = "EN VIVO · 1T" if minute <= 45 else "EN VIVO · 2T"
    elif minute > 45 and state.get("status") == "EN VIVO · 1T":
        state["status"] = "EN VIVO · 2T"

    if ev_type == "GOAL":
        if event_data.get("home_score_override") is not None and event_data.get("away_score_override") is not None:
            state["home_score"] = int(event_data["home_score_override"])
            state["away_score"] = int(event_data["away_score_override"])
        elif team == "HOME":
            state["home_score"] = state.get("home_score", 0) + 1
        elif team == "AWAY":
            state["away_score"] = state.get("away_score", 0) + 1
    elif ev_type == "MATCH_END":
        state["status"] = "FINALIZADO"

    state["updated_at"] = datetime.now(timezone.utc).isoformat()
    payload_str = json.dumps({"event": event, "match": state})

    # 1. Publicar en AWS SNS (si está activo en el entorno AWS)
    sns_msg_id = None
    if sns_client and SNS_TOPIC_ARN:
        try:
            resp = sns_client.publish(
                TopicArn=SNS_TOPIC_ARN,
                Message=payload_str,
                Subject=f"UNAL-{ev_type}-Min{minute}",
                MessageAttributes={
                    "priority": {"DataType": "String", "StringValue": priority},
                    "channel": {"DataType": "String", "StringValue": primary_channel},
                    "event_type": {"DataType": "String", "StringValue": ev_type}
                }
            )
            sns_msg_id = resp.get("MessageId")
        except Exception:
            sns_msg_id = "local-fallback"

    # 2. Guardar en Caché Redis y emitir Fan-Out Pub/Sub al Portal de Aficionados
    fanout_increment = simulated_readers_override if simulated_readers_override > 0 else max(1, active_sse_clients["vivo"] + active_sse_clients["resumen"])
    if redis_client:
        try:
            pipe = redis_client.pipeline()
            pipe.set("match:state", json.dumps(state))
            pipe.rpush("match:events", json.dumps(event))
            pipe.ltrim("match:events", -200, -1)
            pipe.incr("match:metrics:events_published", 1)
            pipe.incrby("match:metrics:fanout_deliveries", fanout_increment)
            pipe.publish("channel:vivo", payload_str)
            if priority == "HIGH" or ev_type in {"YELLOW_CARD", "SUBSTITUTION"}:
                pipe.publish("channel:resumen", payload_str)
            pipe.execute()
        except Exception:
            pass

    # 3. Actualizar memoria local (para modo sin Redis)
    local_match.update(state)
    local_events.append(event)
    for q in list(local_subscribers_vivo):
        q.append(payload_str)
    if priority == "HIGH" or ev_type in {"YELLOW_CARD", "SUBSTITUTION"}:
        for q in list(local_subscribers_resumen):
            q.append(payload_str)

    elapsed_ms = round((time.perf_counter() - t0) * 1000, 2)
    with metrics_lock:
        latency_samples.append(elapsed_ms)
        total_events_published += 1
        total_fanout_deliveries += fanout_increment

    event["fanout_latency_ms"] = elapsed_ms
    event["sns_message_id"] = sns_msg_id or "redis-pubsub-direct"
    return {"event": event, "match": state, "latency_ms": elapsed_ms}


# ==============================================================================
# EXTRACCIÓN REAL DE AUDIO CON FFMPEG + TRANSCRIPCIÓN + OPENROUTER IA
# ==============================================================================
FREE_OPENROUTER_MODELS = [
    "openrouter/free",
    "nvidia/nemotron-3.5-lightning:free",
    "google/gemma-4-31b-it:free",
    "google/gemma-4-26b-a4b-it:free",
    "nvidia/nemotron-3-ultra-550b-a55b:free"
]


def extract_and_transcribe_media_chunk(file_path: Path, start_sec: float, duration_sec: float = 12.0) -> str:
    """
    Extrae el fragmento de audio real [start_sec, start_sec + duration_sec] del archivo de video/audio
    subido (ej. Bayern M. 4-3 Real Madrid.mp4) usando FFmpeg y lo transcribe a texto en español.
    """
    if not file_path.exists() or not sr:
        return ""
    try:
        cmd = [
            "ffmpeg", "-y",
            "-ss", str(max(0.0, round(start_sec, 1))),
            "-t", str(round(duration_sec, 1)),
            "-i", str(file_path),
            "-vn", "-ac", "1", "-ar", "16000", "-f", "wav", "pipe:1"
        ]
        proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=10)
        if not proc.stdout or len(proc.stdout) < 1000:
            return ""
        recognizer = sr.Recognizer()
        with sr.AudioFile(io.BytesIO(proc.stdout)) as source:
            audio_data = recognizer.record(source)
        text = recognizer.recognize_google(audio_data, language="es-ES")
        return text.strip()
    except Exception:
        return ""


def fallback_parse_narrator_text(transcript: str, current_state: dict, video_minute: int | None = None) -> dict:
    """Analizador semántico de respaldo si todos los proveedores gratuitos de OpenRouter están saturados."""
    text_lower = transcript.lower()
    home = current_state.get("home_team", "Equipo Local")
    away = current_state.get("away_team", "Equipo Visitante")

    vs_match = re.search(r"(?:entre|partido)\s+([A-ZÁÉÍÓÚÑa-záéíóúñ\s]{3,22}?)\s+(?:y|contra|vs\.?)\s+([A-ZÁÉÍÓÚÑa-záéíóúñ\s]{3,22}?)(?:[,\.\!]|marcador|en el|$)", transcript)
    if vs_match:
        cand_h = vs_match.group(1).strip()
        cand_a = vs_match.group(2).strip()
        if len(cand_h) >= 3 and len(cand_a) >= 3:
            home = cand_h
            away = cand_a

    min_match = re.search(r"minuto\s+(\d{1,3})", text_lower)
    minute = int(min_match.group(1)) if min_match else (video_minute or max(1, int(current_state.get("minute", 0)) + 1))

    if any(w in text_lower for w in ["arranca el partido", "inicia el partido", "partido en marcha", "pitazo inicial", "orden del juez"]):
        ev_type = "MATCH_START"
    elif any(w in text_lower for w in ["penal", "penalti", "punto blanco"]):
        ev_type = "PENALTY"
    elif any(w in text_lower for w in [
        "gol", "goool", "goooool", "golazo", "anota el", "empata el partido",
        "comienza a ganar", "para poner", "pone el 1", "pone el 2", "pone el 3", "pone el 4"
    ]):
        ev_type = "GOAL"
    elif any(w in text_lower for w in ["roja", "expulsado", "expulsión"]):
        ev_type = "RED_CARD"
    elif any(w in text_lower for w in ["amarilla", "amonestado"]):
        ev_type = "YELLOW_CARD"
    elif any(w in text_lower for w in ["cambio", "sustitución", "entra a la cancha"]):
        ev_type = "SUBSTITUTION"
    else:
        ev_type = "COMMENT"

    team = "NEUTRAL"
    home_tokens = [t for t in home.lower().split() if len(t) >= 4]
    away_tokens = [t for t in away.lower().split() if len(t) >= 4]
    home_score_ov = None
    away_score_ov = None

    for ht in home_tokens:
        for at in away_tokens:
            m1 = re.search(rf"{re.escape(ht)}\s*(\d+)\s+.*?{re.escape(at)}\s*(\d+)", text_lower)
            m2 = re.search(rf"{re.escape(at)}\s*(\d+)\s+.*?{re.escape(ht)}\s*(\d+)", text_lower)
            if m1:
                home_score_ov, away_score_ov = int(m1.group(1)), int(m1.group(2))
                team = "HOME" if home_score_ov > away_score_ov else "AWAY"
            elif m2:
                away_score_ov, home_score_ov = int(m2.group(1)), int(m2.group(2))
                team = "AWAY" if away_score_ov > home_score_ov else "HOME"

    if team == "NEUTRAL":
        if any(f"ganar el {t}" in text_lower or f"gol de {t}" in text_lower or f"gol del {t}" in text_lower for t in home_tokens):
            team = "HOME"
        elif any(f"ganar el {t}" in text_lower or f"gol de {t}" in text_lower or f"gol del {t}" in text_lower for t in away_tokens):
            team = "AWAY"
        elif any(t in text_lower for t in home_tokens) and not any(t in text_lower for t in away_tokens):
            team = "HOME"
        elif any(t in text_lower for t in away_tokens) and not any(t in text_lower for t in home_tokens):
            team = "AWAY"

    player = "Narración en Vivo"
    player_match = re.search(r"(?:de|para|por|entra|sobre|saca|remata)\s+([A-ZÁÉÍÓÚÑ][a-záéíóúñ]+(?:\s+[A-ZÁÉÍÓÚÑ][a-záéíóúñ]+){0,1})", transcript)
    if player_match:
        cand_p = player_match.group(1).strip()
        if cand_p.lower() not in {home.lower(), away.lower(), "el", "la", "cancha", "partido"}:
            player = cand_p

    return {
        "type": ev_type,
        "team": team,
        "home_team": home,
        "away_team": away,
        "home_score_override": home_score_ov,
        "away_score_override": away_score_ov,
        "minute": minute,
        "player": player,
        "description": transcript.strip(),
        "ai_generated": True,
        "ai_model": "OpenRouter Fallback NLP"
    }


def interpret_narrator_with_openrouter(transcript: str, current_state: dict, video_minute: int | None = None) -> dict:
    """
    Envía el texto transcrito del narrador a OpenRouter para que el LLM estructure el evento JSON,
    detecte equipos, jugador, minuto y tipo de jugada.
    """
    api_key = os.environ.get("OPENROUTER_API_KEY", OPENROUTER_API_KEY)
    if not api_key or not http_requests:
        return fallback_parse_narrator_text(transcript, current_state, video_minute)

    est_min = video_minute if video_minute is not None else max(1, int(current_state.get("minute", 0)) + 1)
    system_prompt = (
        "Eres un analista de fútbol en vivo que estructura lo que dice el comentarista de un partido. "
        "Responde UNICAMENTE con un objeto JSON válido (sin markdown ni texto extra) con estas claves exactas:\n"
        "{\n"
        '  "type": "GOAL" | "PENALTY" | "RED_CARD" | "YELLOW_CARD" | "SUBSTITUTION" | "MATCH_START" | "MATCH_END" | "COMMENT",\n'
        '  "team": "HOME" | "AWAY" | "NEUTRAL",\n'
        '  "home_team": "Nombre del equipo local",\n'
        '  "away_team": "Nombre del equipo visitante",\n'
        '  "minute": numero_entero_del_minuto,\n'
        '  "player": "Nombre del jugador protagonista (ej: Vinícius Jr., Musiala, Kane, etc.) o Relato en Vivo",\n'
        '  "description": "Relato periodístico claro y emocionante en español de lo ocurrido en este fragmento"\n'
        "}\n"
        "Regla importante: Clasifica como GOAL si el comentarista canta un gol o menciona que un equipo anota, empata, pasa a ganar o cambia el marcador (ej: 'comienza a ganar el Madrid', 'para poner Real Madrid 1 Bayern 0', 'golazo', etc.). "
        "Si es una jugada de ataque en trámite, pase o narración general sin cambio de marcador, clasifícalo como COMMENT."
    )

    user_prompt = (
        f"Partido actual: Local='{current_state.get('home_team')}' ({current_state.get('home_score')}) vs "
        f"Visitante='{current_state.get('away_team')}' ({current_state.get('away_score')}), Minuto estimado={est_min}.\n"
        f"Transcripción de voz del comentarista: \"{transcript}\""
    )

    for model_name in dict.fromkeys(FREE_OPENROUTER_MODELS):
        try:
            resp = http_requests.post(
                "https://openrouter.ai/api/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                    "HTTP-Referer": "http://localhost:8000",
                    "X-Title": "UNAL Sports Live Fan-Out"
                },
                json={
                    "model": model_name,
                    "messages": [
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_prompt}
                    ],
                    "temperature": 0.1,
                    "max_tokens": 220
                },
                timeout=6.0
            )
            if resp.status_code == 200:
                body_json = resp.json()
                used_model = body_json.get("model", model_name)
                content = body_json["choices"][0]["message"]["content"].strip()
                json_match = re.search(r"\{.*\}", content, re.DOTALL)
                if json_match:
                    parsed = json.loads(json_match.group(0))
                    parsed["ai_generated"] = True
                    parsed["ai_model"] = f"OpenRouter ({used_model})"
                    return parsed
        except Exception:
            continue

    return fallback_parse_narrator_text(transcript, current_state, est_min)


# ==============================================================================
# VISTAS SEPARADAS: PORTAL PÚBLICO DE AFICIONADOS vs. CABINA DEL PERIODISTA
# ==============================================================================
@app.get("/")
def index():
    if SERVICE_ROLE == "journalist":
        return render_template("periodista.html", hostname=HOSTNAME, service_role="journalist-studio")
    return render_template("index.html", hostname=HOSTNAME, service_role="fan-portal")


@app.get("/periodista")
@app.get("/cabina")
def journalist_console():
    return render_template("periodista.html", hostname=HOSTNAME, service_role=SERVICE_ROLE)


@app.get("/health")
def health():
    redis_ok = False
    if redis_client:
        try:
            redis_ok = bool(redis_client.ping())
        except Exception:
            redis_ok = False
    return jsonify(
        status="ok",
        service=f"gtn-proyecto-06-{SERVICE_ROLE}",
        role=SERVICE_ROLE,
        node=HOSTNAME,
        redis_connected=redis_ok,
        sns_configured=bool(SNS_TOPIC_ARN),
        openrouter_configured=bool(os.environ.get("OPENROUTER_API_KEY", OPENROUTER_API_KEY)),
        active_connections=active_sse_clients,
        timestamp=datetime.now(timezone.utc).isoformat()
    )


# ==============================================================================
# ENDPOINTS DE ARCHIVOS MULTIMEDIA Y EXTRACCIÓN DE VOZ REAL DEL VIDEO
# ==============================================================================
@app.get("/api/media/list")
def api_media_list():
    """Lista los videos/audios reales colocados en solucion_proyecto/app/media/."""
    files = []
    for p in sorted(MEDIA_DIR.iterdir()):
        if p.is_file() and p.suffix.lower() in ALLOWED_MEDIA_EXT:
            inferred = infer_teams_from_filename(p.name)
            files.append({
                "filename": p.name,
                "url": f"/media/{p.name}",
                "size_mb": round(p.stat().st_size / (1024 * 1024), 2),
                "inferred_home": inferred[0] if inferred else "",
                "inferred_away": inferred[1] if inferred else ""
            })

    return jsonify(
        media_dir=str(MEDIA_DIR),
        files=files,
        openrouter_ready=bool(os.environ.get("OPENROUTER_API_KEY", OPENROUTER_API_KEY))
    )


@app.post("/api/media/upload")
def api_media_upload():
    if "file" not in request.files:
        return jsonify(error="No se envió archivo"), 400
    f = request.files["file"]
    if not f.filename:
        return jsonify(error="Nombre de archivo vacío"), 400
    ext = Path(f.filename).suffix.lower()
    if ext not in ALLOWED_MEDIA_EXT:
        return jsonify(error=f"Formato no soportado ({ext}). Usa MP4, WEBM, MP3, WAV o M4A."), 400

    safe_name = secure_filename(f.filename)
    dest = MEDIA_DIR / safe_name
    f.save(dest)
    inferred = infer_teams_from_filename(f.filename)
    return jsonify(
        status="uploaded",
        filename=safe_name,
        url=f"/media/{safe_name}",
        inferred_home=inferred[0] if inferred else "",
        inferred_away=inferred[1] if inferred else "",
        saved_in=str(dest)
    ), 201


def resolve_media_file(filename: str) -> Path | None:
    """
    Busca el archivo en MEDIA_DIR tolerando espacios al inicio/final en el nombre del archivo
    (por ejemplo ' Bayern M. 4-3 Real Madrid.mp4').
    """
    if not filename:
        return None
    direct = (MEDIA_DIR / filename).resolve()
    if direct.exists() and direct.parent == MEDIA_DIR.resolve():
        return direct
    stripped = filename.strip()
    for p in MEDIA_DIR.iterdir():
        if p.is_file() and (p.name == filename or p.name.strip() == stripped):
            return p.resolve()
    return None


@app.get("/media/<path:filename>")
def serve_media(filename: str):
    resolved = resolve_media_file(filename)
    if resolved:
        return send_from_directory(MEDIA_DIR, resolved.name)
    return send_from_directory(MEDIA_DIR, filename)


@app.post("/api/ai/process-video-chunk")
def api_process_video_chunk():
    """
    Recibe el nombre del video en reproducción y el segundo actual (`start_sec`).
    Extrae el audio real del video con FFmpeg, lo transcribe a texto con SpeechRecognition
    y se lo envía a OpenRouter para publicar automáticamente la jugada en el Portal de Espectadores.
    """
    token = request.headers.get("X-Journalist-Token") or (request.json or {}).get("token")
    if token != JOURNALIST_TOKEN:
        return jsonify(error="No autorizado."), 401

    body = request.get_json(silent=True) or {}
    raw_filename = str(body.get("filename", ""))
    start_sec = float(body.get("start_sec", 0.0))
    duration_sec = float(body.get("duration_sec", 12.0))
    video_duration = float(body.get("video_duration") or 0.0)

    target_path = resolve_media_file(raw_filename)
    if not target_path:
        return jsonify(error=f"Archivo no encontrado en app/media: {raw_filename}"), 404
    filename = target_path.name

    # 1. Extraer audio real del video y transcribir la voz del comentarista
    transcript = extract_and_transcribe_media_chunk(target_path, start_sec, duration_sec)
    if not transcript:
        return jsonify(status="silence", message="Sin voz clara en este fragmento de audio"), 200

    # Calcular minuto proporcional del partido o usar progresión real
    current_state = get_match_state()
    inferred = infer_teams_from_filename(filename)
    if inferred and current_state.get("home_team") == "Equipo Local":
        current_state["home_team"], current_state["away_team"] = inferred

    if video_duration > 10:
        est_minute = max(1, min(90, int((start_sec / video_duration) * 90) + 1))
    else:
        est_minute = max(1, int(start_sec // 8) + 1)

    # 2. Interpretar la transcripción real con OpenRouter LLM
    ai_event = interpret_narrator_with_openrouter(transcript, current_state, video_minute=est_minute)

    # 3. Publicar automáticamente al Portal de Espectadores (SNS -> SQS -> Redis -> SSE)
    result = publish_event_fanout(ai_event)
    return jsonify(
        status="ai_published",
        chunk_start_sec=round(start_sec, 1),
        transcript_received=transcript,
        ai_interpretation=ai_event,
        **result
    ), 201


@app.post("/api/ai/narrate")
def api_ai_narrate():
    """
    Opción 2: Recibe una frase del micrófono en vivo o escrita por el comentarista,
    la envía a OpenRouter y publica la jugada en el Portal de Espectadores.
    """
    token = request.headers.get("X-Journalist-Token") or (request.json or {}).get("token")
    if token != JOURNALIST_TOKEN:
        return jsonify(error="No autorizado. Token de periodista inválido."), 401

    body = request.get_json(silent=True) or {}
    transcript = str(body.get("transcript", "")).strip()
    if not transcript:
        return jsonify(error="Se requiere el texto/transcripción del comentarista."), 400

    video_minute = body.get("video_minute")
    current_state = get_match_state()

    ai_event = interpret_narrator_with_openrouter(transcript, current_state, video_minute)
    result = publish_event_fanout(ai_event)
    return jsonify(
        status="ai_published",
        transcript_received=transcript,
        ai_interpretation=ai_event,
        **result
    ), 201


@app.post("/api/match/setup")
def api_match_setup():
    """Configura equipos o reinicia el tablero completamente en blanco (0-0, 0 eventos)."""
    token = request.headers.get("X-Journalist-Token") or (request.json or {}).get("token")
    if token != JOURNALIST_TOKEN:
        return jsonify(error="No autorizado."), 401

    body = request.get_json(silent=True) or {}
    if body.get("blank_reset"):
        blank = dict(DEFAULT_MATCH)
        blank["updated_at"] = datetime.now(timezone.utc).isoformat()
        save_match_state(blank, clear_events=True)
        return jsonify(status="blank_reset", match=blank)

    state = get_match_state()
    if body.get("home_team"):
        state["home_team"] = str(body["home_team"]).strip()
    if body.get("away_team"):
        state["away_team"] = str(body["away_team"]).strip()
    if body.get("tournament"):
        state["tournament"] = str(body["tournament"]).strip()
    if body.get("reset_score"):
        state["home_score"] = 0
        state["away_score"] = 0
        state["minute"] = 0
        state["status"] = "EN VIVO · 1T"

    save_match_state(state, clear_events=bool(body.get("clear_events", False)))
    return jsonify(status="updated", match=state)


@app.get("/api/summary")
def api_summary():
    t0 = time.perf_counter()
    state = get_match_state()
    events = get_all_events(limit=100)

    highlights = [
        e for e in events
        if e.get("priority") == "HIGH" or e.get("type") in {"GOAL", "RED_CARD", "YELLOW_CARD", "PENALTY"}
    ]
    stats = {
        "total_events": len(events),
        "goals_home": state.get("home_score", 0),
        "goals_away": state.get("away_score", 0),
        "yellow_cards": sum(1 for e in events if e.get("type") == "YELLOW_CARD"),
        "red_cards": sum(1 for e in events if e.get("type") == "RED_CARD"),
        "substitutions": sum(1 for e in events if e.get("type") == "SUBSTITUTION"),
    }
    cache_latency_ms = round((time.perf_counter() - t0) * 1000, 2)
    with metrics_lock:
        latency_samples.append(cache_latency_ms)

    return jsonify(
        match=state,
        highlights=highlights,
        events=events,
        stats=stats,
        served_by_node=HOSTNAME,
        cache_hit=bool(redis_client),
        latency_ms=cache_latency_ms
    )


@app.post("/api/events")
def api_create_event():
    token = request.headers.get("X-Journalist-Token") or (request.json or {}).get("token")
    if token != JOURNALIST_TOKEN:
        return jsonify(error="No autorizado. Token de periodista inválido."), 401

    data = request.get_json(silent=True) or {}
    if not data.get("description") and not data.get("type"):
        return jsonify(error="Se requiere 'type' y 'description' del evento."), 400

    result = publish_event_fanout(data)
    return jsonify(
        status="published",
        fanout_pattern="SNS_SQS_REDIS_SSE",
        published_by_service=SERVICE_ROLE,
        node=HOSTNAME,
        **result
    ), 201


@app.get("/api/stream/<channel>")
def api_stream(channel: str):
    channel = "resumen" if channel.lower() == "resumen" else "vivo"

    def event_stream():
        active_sse_clients[channel] += 1
        if redis_client:
            try:
                redis_client.incr(f"match:sse:{channel}", 1)
            except Exception:
                pass
        pubsub = None
        local_q = deque()
        try:
            init_payload = json.dumps({
                "type": "CONNECTED",
                "channel": channel,
                "node": HOSTNAME,
                "match": get_match_state()
            })
            yield f"event: connected\ndata: {init_payload}\n\n"

            if redis_client:
                try:
                    pubsub = redis_client.pubsub(ignore_subscribe_messages=True)
                    pubsub.subscribe(f"channel:{channel}")
                except Exception:
                    pubsub = None

            if not pubsub:
                if channel == "vivo":
                    local_subscribers_vivo.append(local_q)
                else:
                    local_subscribers_resumen.append(local_q)

            last_heartbeat = time.time()
            poll_interval = 0.15 if channel == "vivo" else 0.6

            while True:
                sent = False
                if pubsub:
                    msg = pubsub.get_message(timeout=poll_interval)
                    if msg and msg.get("type") == "message":
                        data_str = msg.get("data")
                        yield f"event: match_event\ndata: {data_str}\n\n"
                        sent = True
                else:
                    while local_q:
                        data_str = local_q.popleft()
                        yield f"event: match_event\ndata: {data_str}\n\n"
                        sent = True
                    time.sleep(poll_interval)

                now = time.time()
                if not sent and (now - last_heartbeat) >= 15.0:
                    hb = json.dumps({"ts": now, "node": HOSTNAME, "channel": channel})
                    yield f"event: heartbeat\ndata: {hb}\n\n"
                    last_heartbeat = now
        except GeneratorExit:
            pass
        finally:
            active_sse_clients[channel] = max(0, active_sse_clients[channel] - 1)
            if redis_client:
                try:
                    redis_client.decr(f"match:sse:{channel}", 1)
                except Exception:
                    pass
            if pubsub:
                try:
                    pubsub.close()
                except Exception:
                    pass
            if local_q in local_subscribers_vivo:
                local_subscribers_vivo.remove(local_q)
            if local_q in local_subscribers_resumen:
                local_subscribers_resumen.remove(local_q)

    headers = {
        "Content-Type": "text/event-stream",
        "Cache-Control": "no-cache, no-transform",
        "Connection": "keep-alive",
        "X-Accel-Buffering": "no",
        "X-Served-By-Node": HOSTNAME
    }
    return Response(stream_with_context(event_stream()), headers=headers)


@app.get("/api/metrics")
def api_metrics():
    with metrics_lock:
        samples = sorted(latency_samples) if latency_samples else [0.0]
    n = len(samples)
    p50 = samples[int(n * 0.50)]
    p95 = samples[min(n - 1, int(n * 0.95))]
    p99 = samples[min(n - 1, int(n * 0.99))]
    avg = round(sum(samples) / n, 2)

    ev_pub = total_events_published
    fanout_del = total_fanout_deliveries
    sse_vivo = active_sse_clients["vivo"]
    sse_res = active_sse_clients["resumen"]

    if redis_client:
        try:
            ev_pub = int(redis_client.get("match:metrics:events_published") or ev_pub)
            fanout_del = int(redis_client.get("match:metrics:fanout_deliveries") or fanout_del)
            sse_vivo = max(sse_vivo, int(redis_client.get("match:sse:vivo") or 0))
            sse_res = max(sse_res, int(redis_client.get("match:sse:resumen") or 0))
        except Exception:
            pass

    return jsonify(
        node=HOSTNAME,
        service_role=SERVICE_ROLE,
        active_sse_vivo=sse_vivo,
        active_sse_resumen=sse_res,
        total_active_readers=sse_vivo + sse_res,
        total_events_published=ev_pub,
        total_fanout_deliveries=fanout_del,
        openrouter_ready=bool(os.environ.get("OPENROUTER_API_KEY", OPENROUTER_API_KEY)),
        latency_ms={
            "avg": avg,
            "p50": round(p50, 2),
            "p95": round(p95, 2),
            "p99": round(p99, 2),
            "samples": n
        },
        architecture={
            "cache_engine": "Redis (ElastiCache / Docker)" if redis_client else "In-Memory Fallback",
            "fanout_broker": "AWS SNS + SQS + Redis Pub/Sub" if SNS_TOPIC_ARN else "Redis Pub/Sub + SSE Fan-Out",
            "ai_engine": f"OpenRouter ({OPENROUTER_MODEL})",
            "priority_channels": ["vivo (HIGH priority, 150ms poll)", "resumen (LOW priority / digest, 600ms poll)"]
        }
    )


@app.post("/api/simulate-peak")
def api_simulate_peak():
    body = request.get_json(silent=True) or {}
    simulated_readers = int(body.get("readers", 1000))
    state = get_match_state()
    h_name = state.get("home_team", "Equipo Local")
    a_name = state.get("away_team", "Equipo Visitante")
    burst_events = [
        {"minute": 81, "type": "YELLOW_CARD", "team": "HOME", "player": "Defensa Central (#4)", "description": f"Amarilla en {h_name} por cortar un avance prometedor."},
        {"minute": 84, "type": "SUBSTITUTION", "team": "AWAY", "player": "Cambio Ofensivo (#19)", "description": f"Variante en {a_name} para buscar el resultado en los minutos finales."},
        {"minute": 88, "type": "PENALTY", "team": "AWAY", "player": "Delantero (#9)", "description": f"¡PENAL PARA {a_name.upper()}! El árbitro señala el punto blanco en el área."},
        {"minute": 89, "type": "GOAL", "team": "AWAY", "player": "Delantero (#9)", "description": f"¡GOOOOL DE {a_name.upper()}! Cobro potente para igualar las acciones al 89'."},
        {"minute": 90, "type": "GOAL", "team": "HOME", "player": "Capitán (#10)", "description": f"¡AGÓNICO! ¡GOL DE {h_name.upper()} AL 90+2'! Remate al ángulo en el cierre del partido."}
    ]

    t0 = time.perf_counter()
    results = []
    for ev in burst_events:
        res = publish_event_fanout(ev, simulated_readers_override=simulated_readers)
        results.append(res["latency_ms"])

    total_ms = round((time.perf_counter() - t0) * 1000, 2)
    return jsonify(
        status="peak_simulated",
        simulated_concurrent_readers=simulated_readers,
        events_emitted=len(burst_events),
        total_fanout_messages_delivered=simulated_readers * len(burst_events),
        total_processing_ms=total_ms,
        avg_event_latency_ms=round(sum(results) / len(results), 2),
        node=HOSTNAME
    )


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=PORT, debug=False, threaded=True)
