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
GROQ_API_KEY = os.environ.get("GROQ_API_KEY", "")
HOSTNAME = socket.gethostname()

# Memoria deslizante de los últimos fragmentos narrados y memoria dinámica de jugadores aprendidos en el partido actual
recent_transcripts_history = deque(maxlen=4)
discovered_match_players = deque(maxlen=40)

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


def normalize_team_display_name(raw_name: str) -> str:
    """Normaliza mayúsculas/minúsculas y nombres de clubes conocidos (ej. 'Manchester CIty' -> 'Manchester City')."""
    cleaned = re.sub(r"\s+", " ", raw_name.replace("_", " ")).strip(" _-.")
    if not cleaned:
        return cleaned
    low = cleaned.lower()
    known_clubs = {
        "manchester city": "Manchester City",
        "man city": "Manchester City",
        "leipzig": "RB Leipzig",
        "rb leipzig": "RB Leipzig",
        "real madrid": "Real Madrid",
        "bayern m": "Bayern Múnich",
        "bayern munich": "Bayern Múnich",
        "bayern múnich": "Bayern Múnich",
        "barcelona": "FC Barcelona",
        "fc barcelona": "FC Barcelona",
        "arsenal": "Arsenal",
        "liverpool": "Liverpool",
        "psg": "Paris Saint-Germain",
        "inter": "Inter de Milán",
    }
    if low in known_clubs:
        return known_clubs[low]
    return " ".join(w.capitalize() if not w.isupper() or len(w) > 3 else w for w in cleaned.split())


def infer_teams_from_filename(filename: str) -> tuple[str, str] | None:
    """
    Si el usuario sube un archivo como 'Bayern M. 4-3 Real Madrid.mp4' o 'Manchester_CIty_Vs_Leipzig.mp4',
    detecta automáticamente los nombres de los dos equipos (soportando guiones bajos, 'Vs', marcadores, etc.).
    """
    stem = Path(filename).stem.replace("_", " ").strip()
    stem = re.sub(r"\s+", " ", stem)
    # Patrón 1: EquipoA 4-3 EquipoB  o  EquipoA vs EquipoB (con espacios o guiones)
    m = re.search(r"^(.+?)\s+(?:\d+\s*[-:]\s*\d+|vs\.?|contra|[-–])\s+(.+)$", stem, re.IGNORECASE)
    if m:
        t1 = normalize_team_display_name(m.group(1))
        t2 = normalize_team_display_name(m.group(2))
        if len(t1) >= 2 and len(t2) >= 2:
            return t1, t2
    return None


def is_statistical_or_non_live_goal_mention(text: str) -> bool:
    """
    Detecta cuando el comentarista menciona la palabra 'goles' o 'gol' hablando de estadísticas,
    cifras históricas de un jugador (ej. Haaland), jugadas falladas o goles anulados,
    para evitar falsas alarmas de GOL en el tablero.
    """
    low = text.lower()
    false_goal_patterns = [
        r"\b\d+\s+goles\b",
        r"\bgoles\s+en\b",
        r"\bgoles\s+lleva\b",
        r"\bgoles\s+tiene\b",
        r"\bgoles\s+suma\b",
        r"\bgoles\s+con\b",
        r"\bgoles\s+esta\b",
        r"\bgoleador\b",
        r"\bmáximo\s+anotador\b",
        r"\bcifra\s+de\s+goles\b",
        r"\bpromedio\s+de\s+gol\b",
        r"\bhablando\s+de\s+goles\b",
        r"\bsin\s+goles\b",
        r"\bcasi\s+gol\b",
        r"\bse\s+perdió\s+el\s+gol\b",
        r"\bbuscando\s+el\s+gol\b",
        r"\bbusca\s+el\s+gol\b",
        r"\bno\s+fue\s+gol\b",
        r"\bgol\s+anulado\b",
        r"\bfuera\s+de\s+juego\b",
        r"\boffside\b",
        r"\ba\s+punto\s+del\s+gol\b",
        r"\bcerca\s+del\s+gol\b",
    ]
    return any(re.search(pat, low) for pat in false_goal_patterns)


def remember_discovered_players(players_list: list[str] | None, single_player: str = ""):
    """
    Guarda dinámicamente los nombres de jugadores que van apareciendo en la narración del partido actual
    (funciona para cualquier partido: Liverpool vs Chelsea, Bayern vs Madrid, etc.) para inyectarlos
    en el prompt de Whisper Large v3 Turbo en los siguientes fragmentos sin gastar recursos extra.
    """
    ignored = {
        "", "n/a", "na", "ninguno", "none", "null", "narración en vivo", "relato en vivo",
        "autor por confirmar", "por confirmar", "transmisión oficial", "equipo local", "equipo visitante"
    }
    candidates = list(players_list or [])
    if single_player:
        candidates.append(single_player)
    existing_lower = {p.lower() for p in discovered_match_players}
    for raw_p in candidates:
        clean_p = str(raw_p).strip()
        if len(clean_p) >= 3 and clean_p.lower() not in ignored and clean_p.lower() not in existing_lower:
            discovered_match_players.append(clean_p)
            existing_lower.add(clean_p.lower())


def get_recent_goal_event() -> dict | None:
    """Obtiene el último evento de GOL si ocurrió en los últimos 3 fragmentos para permitir confirmar/corregir su autor."""
    events = get_all_events(limit=3)
    for ev in events:
        if ev.get("type") == "GOAL":
            return ev
    return None


def update_latest_goal_in_place(confirmed_player: str, updated_desc: str, state: dict, t0: float) -> dict | None:
    """
    Actualiza el autor y comentario de la tarjeta del último GOL recién cantado (cuando el relator
    confirma el nombre del goleador segundos después en el festejo o la repetición) SIN duplicar el gol en el marcador.
    """
    clean_player = (confirmed_player or "").strip()
    if not clean_player or clean_player.lower() in {"narración en vivo", "relato en vivo", "autor por confirmar", "por confirmar"}:
        return None

    target_event = None
    # 1. Actualizar en memoria local (buscando desde el más reciente en los últimos 3 eventos)
    for idx in range(len(local_events) - 1, max(-1, len(local_events) - 4), -1):
        if local_events[idx].get("type") == "GOAL":
            local_events[idx]["player"] = clean_player
            if updated_desc:
                local_events[idx]["description"] = updated_desc
            local_events[idx]["scorer_confirmed"] = True
            target_event = dict(local_events[idx])
            break

    # 2. Actualizar en Redis si está activo
    if redis_client:
        try:
            total_len = redis_client.llen("match:events")
            for offset in range(1, min(4, total_len + 1)):
                raw_idx = total_len - offset
                raw_item = redis_client.lindex("match:events", raw_idx)
                if raw_item:
                    ev_obj = json.loads(raw_item)
                    if ev_obj.get("type") == "GOAL":
                        ev_obj["player"] = clean_player
                        if updated_desc:
                            ev_obj["description"] = updated_desc
                        ev_obj["scorer_confirmed"] = True
                        redis_client.lset("match:events", raw_idx, json.dumps(ev_obj))
                        target_event = ev_obj
                        break
        except Exception:
            pass

    if not target_event:
        return None

    state["updated_at"] = datetime.now(timezone.utc).isoformat()
    payload_str = json.dumps({"event": target_event, "match": state, "updated_event": True})

    if redis_client:
        try:
            pipe = redis_client.pipeline()
            pipe.set("match:state", json.dumps(state))
            pipe.publish("channel:vivo", payload_str)
            pipe.publish("channel:resumen", payload_str)
            pipe.execute()
        except Exception:
            pass

    for q in list(local_subscribers_vivo):
        q.append(payload_str)
    for q in list(local_subscribers_resumen):
        q.append(payload_str)

    elapsed_ms = round((time.perf_counter() - t0) * 1000, 2)
    target_event["fanout_latency_ms"] = elapsed_ms
    return {"event": target_event, "match": state, "latency_ms": elapsed_ms, "updated_existing_goal": True}


def publish_event_fanout(event_data: dict, simulated_readers_override: int = 0) -> dict:
    """
    Implementa el Patrón Fan-Out:
    1. Recibe la jugada (manual o interpretada por la IA desde el video/audio/micrófono).
    2. Si es GOAL_CONFIRMATION (el narrador confirma en la repetición quién hizo el gol recién cantado),
       actualiza el autor de ese gol sin sumar un segundo gol falso.
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
    team = str(event_data.get("team", "NEUTRAL")).upper()
    if team not in {"HOME", "AWAY", "NEUTRAL"}:
        team = "NEUTRAL"

    # Aprender dinámicamente los jugadores mencionados en este fragmento para enriquecer Whisper
    remember_discovered_players(event_data.get("detected_players"), str(event_data.get("player", "")))

    # ¿Es confirmación o corrección del autor del último gol cantado hace pocos segundos (ej. "Lo hizo Arda Güler")?
    recent_goal = get_recent_goal_event()
    if ev_type == "GOAL_CONFIRMATION" and recent_goal:
        updated_res = update_latest_goal_in_place(
            str(event_data.get("player", "")),
            str(event_data.get("description", "")),
            state,
            t0
        )
        if updated_res:
            return updated_res
        ev_type = "COMMENT"

    if ev_type not in {"GOAL", "PENALTY", "RED_CARD", "YELLOW_CARD", "SUBSTITUTION", "COMMENT", "MATCH_START", "MATCH_END"}:
        ev_type = "COMMENT"

    # Barrera Anti-Falsas Alarmas de Gol y Anti-Duplicación en Festejos:
    cur_h = int(state.get("home_score", 0))
    cur_a = int(state.get("away_score", 0))
    ov_h = event_data.get("home_score_override")
    ov_a = event_data.get("away_score_override")
    if ev_type == "GOAL" and bool(event_data.get("ai_generated", False)):
        raw_desc = str(event_data.get("description", ""))
        override_changes_score = (
            ov_h is not None and ov_a is not None and (int(ov_h) > cur_h or int(ov_a) > cur_a)
        )
        # Si hace instantes se cantó gol del mismo equipo y el marcador reportado sigue siendo el mismo, es la repetición confirmando el autor
        if recent_goal and recent_goal.get("team") == team and ov_h is not None and ov_a is not None and int(ov_h) == cur_h and int(ov_a) == cur_a:
            updated_res = update_latest_goal_in_place(
                str(event_data.get("player", "")),
                raw_desc,
                state,
                t0
            )
            if updated_res:
                return updated_res
            ev_type = "COMMENT"
        elif team == "NEUTRAL" and not override_changes_score:
            ev_type = "COMMENT"
        elif ov_h is not None and ov_a is not None and int(ov_h) == cur_h and int(ov_a) == cur_a:
            ev_type = "COMMENT"
        elif is_statistical_or_non_live_goal_mention(raw_desc) and not override_changes_score:
            ev_type = "COMMENT"

    priority, primary_channel = classify_event_priority(ev_type)
    raw_min = event_data.get("minute")
    minute = int(raw_min) if (raw_min is not None and str(raw_min).isdigit()) else max(1, int(state.get("minute", 0)) + 1)

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
# EXTRACCIÓN REAL DE AUDIO CON FFMPEG + WHISPER LARGE V3 TURBO / STT + LLM IA
# ==============================================================================
FREE_OPENROUTER_MODELS = [
    "openrouter/free",
    "nvidia/nemotron-3.5-lightning:free",
    "google/gemma-4-31b-it:free",
    "google/gemma-4-26b-a4b-it:free",
    "nvidia/nemotron-3-ultra-550b-a55b:free"
]

# Diccionario de corrección fonética futbolística (corrige errores típicos de STT con ruido de estadio)
FOOTBALL_PHONETIC_FIXES = [
    (r"\bRoger\b", "Neuer"),
    (r"\broger\b", "Neuer"),
    (r"\bMecano\b", "Upamecano"),
    (r"\bmecano\b", "Upamecano"),
    (r"\bupamecano\b", "Upamecano"),
    (r"\bNavy\b", "Gnabry"),
    (r"\bnavy\b", "Gnabry"),
    (r"\bdías\b", "Díaz"),
    (r"\barda\b", "Arda Güler"),
    (r"\bArda\b", "Arda Güler"),
    (r"\bTurco\b", "Arda Güler"),
    (r"\bvinicius\b", "Vinícius Jr."),
    (r"\bVinicius\b", "Vinícius Jr."),
    (r"\bsane\b", "Leroy Sané"),
    (r"\bSane\b", "Leroy Sané"),
    (r"\bmusiala\b", "Jamal Musiala"),
    (r"\bMusiala\b", "Jamal Musiala"),
    (r"\bkane\b", "Harry Kane"),
    (r"\bKane\b", "Harry Kane"),
    (r"\bkroos\b", "Toni Kroos"),
    (r"\bbellingham\b", "Jude Bellingham"),
    (r"\bmbappe\b", "Kylian Mbappé"),
    (r"\bMbappe\b", "Kylian Mbappé"),
    (r"\bcherqui\b", "Rayan Cherki"),
    (r"\bCherqui\b", "Rayan Cherki"),
    (r"\bcherki\b", "Rayan Cherki"),
    (r"\bnico\s+reyli\b", "Nico O'Reilly"),
    (r"\bNico\s+reyli\b", "Nico O'Reilly"),
    (r"\breyli\b", "Nico O'Reilly"),
    (r"\boreilly\b", "Nico O'Reilly"),
    (r"\bo'reilly\b", "Nico O'Reilly"),
    (r"\bleicey\b", "RB Leipzig"),
    (r"\bLeicey\b", "RB Leipzig"),
    (r"\bleipsig\b", "RB Leipzig"),
    (r"\bleipzig\b", "RB Leipzig"),
    (r"\bhalaand\b", "Erling Haaland"),
    (r"\bHalaand\b", "Erling Haaland"),
    (r"\bhaland\b", "Erling Haaland"),
    (r"\bHaland\b", "Erling Haaland"),
    (r"\bjalan\b", "Erling Haaland"),
    (r"\bJalan\b", "Erling Haaland"),
    (r"\bguardiol\b", "Josko Gvardiol"),
    (r"\bgvardiol\b", "Josko Gvardiol"),
    (r"\bfoden\b", "Phil Foden"),
    (r"\bopenda\b", "Loïs Openda"),
    (r"\bsesko\b", "Benjamin Šeško"),
    (r"\breal madrid\b", "Real Madrid"),
    (r"\bbayern munich\b", "Bayern Múnich"),
    (r"\bbayern\b", "Bayern Múnich"),
    (r"\bmanchester city\b", "Manchester City"),
]

# Plantillas conocidas para asignar con precisión de qué equipo es cada jugador y alimentar el prompt de Whisper
KNOWN_TEAM_PLAYERS = {
    "bayern": ["neuer", "upamecano", "kim", "kimmich", "goretzka", "laimer", "musiala", "sané", "sane", "gnabry", "kane", "müller", "muller", "davies", "guerreiro", "olise", "díaz", "diaz"],
    "madrid": ["lunin", "courtois", "carvajal", "rüdiger", "rudiger", "nacho", "mendy", "valverde", "camavinga", "tchouameni", "kroos", "modric", "bellingham", "vinícius", "vinicius", "rodrygo", "arda", "güler", "guler", "mbappé", "mbappe", "joselu", "brahim"],
    "city": ["haaland", "o'reilly", "cherki", "foden", "de bruyne", "rodri", "bernardo", "gündogan", "gundogan", "gvardiol", "rico lewis", "rúben dias", "akanji", "doku", "savinho", "grealish", "ederson", "ortega", "kovacic", "álvarez", "alvarez"],
    "leipzig": ["openda", "simons", "xavi simons", "šeško", "sesko", "dani olmo", "baumgartner", "haidara", "lukeba", "orbán", "orban", "raum", "henrichs", "gulácsi", "gulacsi", "poulsen"]
}


def apply_football_phonetics(raw_text: str) -> str:
    """Corrige nombres de jugadores mal transcritos por el ruido de ambiente del estadio."""
    cleaned = raw_text.strip()
    for pattern, replacement in FOOTBALL_PHONETIC_FIXES:
        cleaned = re.sub(pattern, replacement, cleaned)
    return cleaned


def extract_and_transcribe_media_chunk(file_path: Path, start_sec: float, duration_sec: float = 15.0, match_state: dict | None = None) -> tuple[str, str]:
    """
    Extrae el fragmento de audio real con solapamiento inteligente de 4s [start_sec - 4s, start_sec + duration_sec]
    para nunca cortar un grito de gol ni el nombre del autor a la mitad, y lo transcribe con:
      1. Whisper Large v3 Turbo (Groq API) enriquecido con la memoria auto-aprendida de jugadores del partido actual.
      2. Google SpeechRecognition en español + corrector fonético futbolístico como respaldo.
    """
    if not file_path.exists():
        return "", "none"

    overlap = min(4.0, start_sec) if start_sec > 0 else 0.0
    actual_start = max(0.0, round(start_sec - overlap, 1))
    actual_dur = round(duration_sec + overlap, 1)

    try:
        cmd = [
            "ffmpeg", "-y",
            "-ss", str(actual_start),
            "-t", str(actual_dur),
            "-i", str(file_path),
            "-vn", "-ac", "1", "-ar", "16000", "-f", "wav", "pipe:1"
        ]
        proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=12)
        if not proc.stdout or len(proc.stdout) < 1000:
            return "", "none"

        groq_key = os.environ.get("GROQ_API_KEY", GROQ_API_KEY).strip()
        home_t = (match_state or {}).get("home_team", "Equipo Local")
        away_t = (match_state or {}).get("away_team", "Equipo Visitante")

        # Construir lista dinámica de jugadores aprendidos en este partido + vocabulario base
        learned_roster = ", ".join(list(discovered_match_players))
        base_vocab = (
            "Erling Haaland, Nico O'Reilly, Rayan Cherki, Phil Foden, Kevin De Bruyne, Rodri, Gvardiol, "
            "Loïs Openda, Xavi Simons, Benjamin Šeško, Antonio Nusa, Dani Olmo, Castello Lukeba, David Raum, "
            "Manuel Neuer, Upamecano, Kimmich, Jamal Musiala, Leroy Sané, Harry Kane, Luis Díaz, Gnabry, Michael Olise, "
            "Lunin, Carvajal, Rüdiger, Toni Kroos, Federico Valverde, Jude Bellingham, Arda Güler, Rodrygo, Vinícius Jr., Kylian Mbappé, "
            "Mohamed Salah, Virgil van Dijk, Mac Allister, Cole Palmer, Moisés Caicedo, Enzo Fernández"
        )
        roster_prompt_str = f"{learned_roster}, {base_vocab}" if learned_roster else base_vocab

        # 1. Usar Whisper Large v3 Turbo + Prompt Dinámico del Partido (Groq API)
        if groq_key and http_requests:
            try:
                football_context_prompt = (
                    f"Relato deportivo de fútbol en vivo en español (ESPN / Champions League / Premier League). "
                    f"Partido entre {home_t} y {away_t}. "
                    f"Jugadores en cancha: {roster_prompt_str}."
                )
                resp = http_requests.post(
                    "https://api.groq.com/openai/v1/audio/transcriptions",
                    headers={"Authorization": f"Bearer {groq_key}"},
                    files={"file": ("chunk.wav", proc.stdout, "audio/wav")},
                    data={
                        "model": "whisper-large-v3-turbo",
                        "language": "es",
                        "prompt": football_context_prompt[:850],
                        "response_format": "json",
                        "temperature": "0.0"
                    },
                    timeout=8.0
                )
                if resp.status_code == 200:
                    whisper_text = resp.json().get("text", "").strip()
                    if whisper_text:
                        return apply_football_phonetics(whisper_text), "Whisper-Large-v3-Turbo (Groq)"
            except Exception:
                pass

        # 2. Respaldo sin llave: SpeechRecognition + Corrector Fonético de Fútbol
        if sr:
            recognizer = sr.Recognizer()
            with sr.AudioFile(io.BytesIO(proc.stdout)) as source:
                audio_data = recognizer.record(source)
            text = recognizer.recognize_google(audio_data, language="es-ES")
            return apply_football_phonetics(text), "SpeechRecognition+FootballDict"
    except Exception:
        pass
    return "", "none"


def build_editorial_commentary(ev_type: str, team_label: str, player: str, corrected_transcript: str, home: str, away: str, h_score: int, a_score: int) -> str:
    """
    Transforma una transcripción hablada en una línea periodística deportiva profesional (con mayúsculas,
    puntuación impecable y estilo minuto a minuto de ESPN/Opta) cuando los modelos de OpenRouter tienen rate-limit.
    """
    clean = corrected_transcript.strip()
    if clean:
        clean = clean[0].upper() + clean[1:]
    if not clean.endswith((".", "!", "?")):
        clean += "."

    if ev_type == "MATCH_START":
        return f"¡Pitazo inicial! Ya se juega el partido entre {home} y {away}. ({clean})"
    if ev_type == "GOAL":
        protagonist = f" por intermedio de {player}" if player and player != "Narración en Vivo" else ""
        return f"¡GOOOOL de {team_label}! Anota el conjunto de {team_label}{protagonist} para sacudir el marcador ({home} {h_score} - {a_score} {away}). Relato en vivo: «{clean}»"
    if ev_type == "PENALTY":
        return f"¡PENAL sancionado en el área! Momento de máxima tensión entre {home} y {away}. «{clean}»"
    if ev_type == "YELLOW_CARD":
        return f"Tarjeta amarilla mostrada por el árbitro ({team_label}). «{clean}»"
    if ev_type == "RED_CARD":
        return f"¡Tarjeta ROJA y expulsión en {team_label}! «{clean}»"
    if ev_type == "SUBSTITUTION":
        return f"Movimiento táctico y variante en la cancha ({team_label}). «{clean}»"

    if player and player != "Narración en Vivo":
        return f"Intervención protagonista de {player} ({team_label}): {clean}"
    return f"Acción en desarrollo ({home} vs {away}): {clean}"


def fallback_parse_narrator_text(transcript: str, current_state: dict, video_minute: int | None = None, context_text: str = "") -> dict:
    """
    Analizador semántico futbolístico con memoria de contexto, detección de plantillas
    y redacción periodística profesional.
    """
    corrected = apply_football_phonetics(transcript)
    combined_context = f"{context_text} {corrected}".strip()
    text_lower = corrected.lower()
    combined_lower = combined_context.lower()

    home = current_state.get("home_team", "Equipo Local")
    away = current_state.get("away_team", "Equipo Visitante")
    cur_h_score = int(current_state.get("home_score", 0))
    cur_a_score = int(current_state.get("away_score", 0))

    min_match = re.search(r"minuto\s+(\d{1,3})", text_lower)
    minute = int(min_match.group(1)) if min_match else (video_minute or max(1, int(current_state.get("minute", 0)) + 1))

    # 1. Clasificar tipo de evento (con filtro anti-falsas alarmas cuando hablan de estadísticas de goles)
    is_stat_goal = is_statistical_or_non_live_goal_mention(text_lower)
    has_live_goal_trigger = bool(re.search(
        r"\b(gol|go+l|golazo)\b|anota el|empata el|lo empata|comienza a ganar|pone el [1-9]|1 a 1|uno a uno|2 a 1|dos a uno|1 a 0|uno a cero",
        text_lower
    ))

    if any(w in text_lower for w in ["arranca el partido", "inicia el partido", "partido en marcha", "pitazo inicial", "orden del juez"]):
        ev_type = "MATCH_START"
    elif any(w in text_lower for w in ["penal", "penalti", "punto blanco"]):
        ev_type = "PENALTY"
    elif has_live_goal_trigger and not is_stat_goal:
        ev_type = "GOAL"
    elif any(w in text_lower for w in ["roja", "expulsado", "expulsión"]):
        ev_type = "RED_CARD"
    elif any(w in text_lower for w in ["amarilla", "amonestado"]):
        ev_type = "YELLOW_CARD"
    elif any(w in text_lower for w in ["cambio", "sustitución", "entra a la cancha"]):
        ev_type = "SUBSTITUTION"
    else:
        ev_type = "COMMENT"

    # 2. Detectar jugador protagonista (priorizando SIEMPRE el fragmento actual sobre el contexto previo)
    player = "Narración en Vivo"
    detected_player_team = None
    famous_players = [
        ("Erling Haaland", "city"), ("Nico O'Reilly", "city"), ("Rayan Cherki", "city"),
        ("Phil Foden", "city"), ("Kevin De Bruyne", "city"), ("Rodri", "city"),
        ("Bernardo Silva", "city"), ("Josko Gvardiol", "city"), ("Rico Lewis", "city"),
        ("Jeremy Doku", "city"), ("Savinho", "city"), ("Jack Grealish", "city"),
        ("Rúben Dias", "city"), ("Manuel Akanji", "city"), ("Ederson", "city"),
        ("Xavi Simons", "leipzig"), ("Loïs Openda", "leipzig"), ("Benjamin Šeško", "leipzig"),
        ("Dani Olmo", "leipzig"), ("Castello Lukeba", "leipzig"), ("David Raum", "leipzig"),
        ("Péter Gulácsi", "leipzig"),
        ("Kylian Mbappé", "madrid"), ("Vinícius Jr.", "madrid"), ("Rodrygo", "madrid"),
        ("Jude Bellingham", "madrid"), ("Arda Güler", "madrid"), ("Toni Kroos", "madrid"),
        ("Valverde", "madrid"), ("Camavinga", "madrid"), ("Rüdiger", "madrid"),
        ("Carvajal", "madrid"), ("Lunin", "madrid"), ("Courtois", "madrid"),
        ("Harry Kane", "bayern"), ("Jamal Musiala", "bayern"), ("Michael Olise", "bayern"),
        ("Leroy Sané", "bayern"), ("Gnabry", "bayern"), ("Müller", "bayern"),
        ("Luis Díaz", "bayern"), ("Díaz", "bayern"), ("Kimmich", "bayern"),
        ("Goretzka", "bayern"), ("Laimer", "bayern"), ("Upamecano", "bayern"),
        ("Kim", "bayern"), ("Neuer", "bayern")
    ]
    # Pasada 1: Buscar jugador en el fragmento ACTUAL (text_lower)
    for p_name, p_club in famous_players:
        last_token = p_name.split()[-1].lower().rstrip(".")
        if p_name.lower() in text_lower or (len(last_token) >= 4 and last_token in text_lower):
            player = p_name
            detected_player_team = p_club
            break
    # Pasada 2: Solo si es GOL y en este fragmento no se dijo el nombre, buscar en el contexto inmediatamente anterior
    if player == "Narración en Vivo" and ev_type == "GOAL" and context_text:
        ctx_lower = context_text.lower()
        for p_name, p_club in famous_players:
            last_token = p_name.split()[-1].lower().rstrip(".")
            if p_name.lower() in ctx_lower or (len(last_token) >= 4 and last_token in ctx_lower):
                player = p_name
                detected_player_team = p_club
                break

    # 3. Identificar equipo protagonista (HOME vs AWAY) con lógica de empate y marcador explícito
    team = "NEUTRAL"
    home_tokens = [t.rstrip(".") for t in home.lower().split() if len(t.rstrip(".")) >= 4]
    away_tokens = [t.rstrip(".") for t in away.lower().split() if len(t.rstrip(".")) >= 4]
    home_score_ov = None
    away_score_ov = None

    # ¿El relator menciona empate ("empata", "1 a 1", "uno a uno")? Si es así, el gol es del equipo que iba abajo en el marcador
    is_equalizer = ev_type == "GOAL" and any(
        w in text_lower for w in ["empata", "igualdad", "1 a 1", "uno a uno", "2 a 2", "dos a dos", "3 a 3"]
    )
    if is_equalizer:
        if cur_h_score < cur_a_score:
            team = "HOME"
            home_score_ov, away_score_ov = cur_a_score, cur_a_score
        elif cur_a_score < cur_h_score:
            team = "AWAY"
            home_score_ov, away_score_ov = cur_h_score, cur_h_score

    # ¿Menciona explícitamente "gol del <equipo>" o "gana el <equipo>" en el fragmento actual?
    if team == "NEUTRAL":
        if any(f"gol de {t}" in text_lower or f"gol del {t}" in text_lower or f"gana el {t}" in text_lower or f"ganar el {t}" in text_lower for t in home_tokens):
            team = "HOME"
        elif any(f"gol de {t}" in text_lower or f"gol del {t}" in text_lower or f"gana el {t}" in text_lower or f"ganar el {t}" in text_lower for t in away_tokens):
            team = "AWAY"

    # Si hay un jugador detectado en el fragmento actual, usar su club (salvo que haya sido empate forzado del otro club)
    if team == "NEUTRAL" and detected_player_team:
        club_keywords = {
            "bayern": "bayern",
            "madrid": "madrid",
            "city": "city",
            "leipzig": "leipzig"
        }
        kw = club_keywords.get(detected_player_team, "")
        if kw:
            if kw in home.lower():
                team = "HOME"
            elif kw in away.lower():
                team = "AWAY"

    # Si fue empate de HOME pero el jugador detectado era del AWAY (ej. decía "frente al Real Madrid"), ajustar jugador
    if team == "HOME" and detected_player_team and detected_player_team not in home.lower() and detected_player_team in away.lower():
        player = home
    elif team == "AWAY" and detected_player_team and detected_player_team not in away.lower() and detected_player_team in home.lower():
        player = away

    if team == "NEUTRAL":
        if any(t in text_lower for t in home_tokens) and not any(t in text_lower for t in away_tokens):
            team = "HOME"
        elif any(t in text_lower for t in away_tokens) and not any(t in text_lower for t in home_tokens):
            team = "AWAY"

    # Si después de todo el análisis seguía siendo GOAL pero no hay equipo ni cambio de marcador, es comentario estadístico
    if ev_type == "GOAL" and team == "NEUTRAL" and home_score_ov is None:
        ev_type = "COMMENT"

    new_h = home_score_ov if home_score_ov is not None else (cur_h_score + (1 if ev_type == "GOAL" and team == "HOME" else 0))
    new_a = away_score_ov if away_score_ov is not None else (cur_a_score + (1 if ev_type == "GOAL" and team == "AWAY" else 0))
    team_label = home if team == "HOME" else (away if team == "AWAY" else f"{home} / {away}")

    editorial_desc = build_editorial_commentary(ev_type, team_label, player, corrected, home, away, new_h, new_a)

    return {
        "type": ev_type,
        "team": team,
        "home_team": home,
        "away_team": away,
        "home_score_override": home_score_ov,
        "away_score_override": away_score_ov,
        "minute": minute,
        "player": player,
        "description": editorial_desc,
        "ai_generated": True,
        "ai_model": "Sports Editorial AI"
    }


def interpret_narrator_with_openrouter(transcript: str, current_state: dict, video_minute: int | None = None) -> dict:
    """
    Envía el texto transcrito del narrador (junto con la memoria de los fragmentos anteriores,
    la lista de jugadores aprendidos dinámicamente y el último gol registrado)
    a Groq LLM (openai/gpt-oss-120b / qwen3.8-27b) para estructurar el JSON deportivo sin adivinar goleadores.
    """
    corrected_transcript = apply_football_phonetics(transcript)
    prev_context = " | ".join(list(recent_transcripts_history)[-2:])
    recent_transcripts_history.append(corrected_transcript)

    groq_key = os.environ.get("GROQ_API_KEY", GROQ_API_KEY).strip()
    est_min = video_minute if video_minute is not None else max(1, int(current_state.get("minute", 0)) + 1)

    recent_goal = get_recent_goal_event()
    recent_goal_str = (
        f"Último GOL registrado hace instantes: Equipo='{recent_goal.get('team_name')}' ({recent_goal.get('team')}), "
        f"Autor registrado='{recent_goal.get('player')}', Minuto={recent_goal.get('minute')}."
        if recent_goal else "Ningún gol registrado en los últimos instantes."
    )
    known_roster_str = ", ".join(list(discovered_match_players)) if discovered_match_players else "En proceso de descubrimiento en el relato"

    system_prompt = (
        "Eres un periodista deportivo senior de ESPN redactando el minuto a minuto en vivo. "
        "Recibes la transcripción de voz del relator (con Whisper Large v3 Turbo) y el contexto previo.\n"
        "REGLAS CRÍTICAS DE PRECISIÓN DEPORTIVA (FUNCIONA PARA CUALQUIER PARTIDO):\n"
        "1. PROHIBIDO ADIVINAR EL GOLEADOR POR FAMA O PASE PREVIO: En un 'GOAL', JAMÁS pongas por defecto a la estrella del equipo "
        "(ej. NO pongas a Mbappé, Haaland o Salah si el relator no dijo explícitamente que él metió el gol) ni confundas a quien dio un pase previo con el autor del gol. "
        "Si el relator grita '¡Gol!' o '¡Gol del Real Madrid!' pero en este fragmento aún no dice claramente el nombre de quién remató al arco, "
        "pon obligatoriamente \"player\": \"Autor por confirmar\". Si menciona explícitamente al autor (ej. 'gol de Arda Güler', 'lo hizo el turco Güler'), pon su nombre exacto.\n"
        "2. CONFIRMACIÓN O CORRECCIÓN DEL AUTOR EN LA REPETICIÓN ('GOAL_CONFIRMATION'): Si en 'Último GOL registrado hace instantes' ya aparece un gol reciente "
        "y en este fragmento el relator está festejando o repitiendo ESE MISMO GOL y confirma quién lo anotó (ej. '¡Qué golazo de Arda Güler para el 1-0!'), "
        "NO sumes otro gol: usa \"type\": \"GOAL_CONFIRMATION\", pon en \"player\" el nombre verdadero del autor ('Arda Güler') y mantén 'home_score_override' y 'away_score_override' iguales al marcador actual.\n"
        "3. REGLA ANTI-FALSOS GOLES POR ESTADÍSTICAS: Si el comentarista menciona cifras históricas o rachas ('lleva 30 goles', 'es el goleador', 'casi gol', 'buscando el gol', 'sin goles'), "
        "PROHIBIDO usar 'GOAL': clasifícalo SIEMPRE como 'COMMENT'.\n"
        "4. EMPATES EN VIVO: Si el relator canta un gol de empate ('1 a 1', 'lo empata'), asigna el GOL al equipo que iba abajo en el marcador.\n"
        "5. AUTO-APRENDIZAJE DE JUGADORES: Incluye en 'detected_players' una lista con todos los nombres de futbolistas mencionados en este fragmento (bien escritos).\n"
        "Responde UNICAMENTE con un objeto JSON válido con estas claves:\n"
        "{\n"
        '  "type": "GOAL" | "GOAL_CONFIRMATION" | "PENALTY" | "RED_CARD" | "YELLOW_CARD" | "SUBSTITUTION" | "MATCH_START" | "MATCH_END" | "COMMENT",\n'
        '  "team": "HOME" | "AWAY" | "NEUTRAL",\n'
        '  "home_team": "Nombre del equipo local",\n'
        '  "away_team": "Nombre del equipo visitante",\n'
        '  "home_score_override": numero_entero_goles_local_actualizado,\n'
        '  "away_score_override": numero_entero_goles_visitante_actualizado,\n'
        '  "minute": numero_entero_del_minuto,\n'
        '  "player": "Nombre confirmado del jugador protagonista o Autor por confirmar",\n'
        '  "detected_players": ["Jugador 1", "Jugador 2"],\n'
        '  "description": "Comentario periodístico profesional con mayúsculas y puntuación impecable"\n'
        "}"
    )

    user_prompt = (
        f"Estado actual del marcador: Local='{current_state.get('home_team')}' ({current_state.get('home_score')}) vs "
        f"Visitante='{current_state.get('away_team')}' ({current_state.get('away_score')}), Minuto={est_min}.\n"
        f"{recent_goal_str}\n"
        f"Jugadores ya identificados en este partido: {known_roster_str}\n"
        f"Contexto inmediatamente anterior: \"{prev_context}\"\n"
        f"Fragmento actual del relator: \"{corrected_transcript}\""
    )

    if groq_key and http_requests:
        for groq_model in ["openai/gpt-oss-120b", "openai/gpt-oss-20b", "qwen/qwen3.8-27b"]:
            try:
                g_resp = http_requests.post(
                    "https://api.groq.com/openai/v1/chat/completions",
                    headers={"Authorization": f"Bearer {groq_key}", "Content-Type": "application/json"},
                    json={
                        "model": groq_model,
                        "messages": [
                            {"role": "system", "content": system_prompt},
                            {"role": "user", "content": user_prompt}
                        ],
                        "temperature": 0.05,
                        "max_tokens": 340,
                        "response_format": {"type": "json_object"}
                    },
                    timeout=5.0
                )
                if g_resp.status_code == 200:
                    content = g_resp.json()["choices"][0]["message"]["content"].strip()
                    parsed = json.loads(content)
                    parsed["ai_generated"] = True
                    parsed["ai_model"] = f"Groq ({groq_model} + Whisper v3 Turbo)"
                    return parsed
            except Exception:
                continue

    return fallback_parse_narrator_text(corrected_transcript, current_state, est_min, context_text=prev_context)


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
        groq_configured=bool(os.environ.get("GROQ_API_KEY", GROQ_API_KEY)),
        discovered_players_count=len(discovered_match_players),
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
        groq_ready=bool(os.environ.get("GROQ_API_KEY", GROQ_API_KEY))
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

    # Obtener estado actual e inferir equipos del archivo antes de transcribir (para dar contexto a Whisper)
    current_state = get_match_state()
    inferred = infer_teams_from_filename(filename)
    if inferred and (
        current_state.get("home_team") in {"Equipo Local", "Local", ""}
        or current_state.get("home_team") != inferred[0]
        or current_state.get("away_team") != inferred[1]
    ):
        discovered_match_players.clear()
        current_state["home_team"], current_state["away_team"] = inferred
        save_match_state(current_state, clear_events=False)

    # 1. Extraer audio real del video y transcribir la voz del comentarista (Whisper Large v3 Turbo o Google STT + Corrección Fonética)
    transcript, stt_engine = extract_and_transcribe_media_chunk(
        target_path, start_sec, duration_sec, match_state=current_state
    )
    if not transcript:
        return jsonify(status="silence", message="Sin voz clara en este fragmento de audio"), 200

    if video_duration > 10:
        est_minute = max(1, min(90, int((start_sec / video_duration) * 90) + 1))
    else:
        est_minute = max(1, int(start_sec // 8) + 1)

    # 2. Interpretar la transcripción real con IA (Groq Llama 3.3 / OpenRouter / Motor Editorial Futbolístico)
    ai_event = interpret_narrator_with_openrouter(transcript, current_state, video_minute=est_minute)
    ai_event["stt_engine"] = stt_engine

    # 3. Publicar automáticamente al Portal de Espectadores (SNS -> SQS -> Redis -> SSE)
    result = publish_event_fanout(ai_event)
    return jsonify(
        status="ai_published",
        chunk_start_sec=round(start_sec, 1),
        stt_engine=stt_engine,
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
        recent_transcripts_history.clear()
        discovered_match_players.clear()
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
        recent_transcripts_history.clear()
        discovered_match_players.clear()
        state["home_score"] = 0
        state["away_score"] = 0
        state["minute"] = 0
        state["status"] = "EN VIVO · 1T"
    if body.get("clear_events"):
        recent_transcripts_history.clear()
        discovered_match_players.clear()

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
        groq_ready=bool(os.environ.get("GROQ_API_KEY", GROQ_API_KEY)),
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
            "ai_engine": "Groq (Whisper Large v3 Turbo + GPT-OSS-120B)",
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
