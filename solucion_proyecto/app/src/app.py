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
import shutil
import socket
import difflib
import subprocess
import threading
import unicodedata
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
_SRC_DIR = Path(__file__).resolve().parent
BASE_APP_DIR = _SRC_DIR if (_SRC_DIR / "iconos").exists() else _SRC_DIR.parent
MEDIA_DIR = BASE_APP_DIR / "media"
MEDIA_DIR.mkdir(parents=True, exist_ok=True)
ESCUDOS_DIR = BASE_APP_DIR / "escudos"
ESCUDOS_DIR.mkdir(parents=True, exist_ok=True)
ICONOS_DIR = BASE_APP_DIR / "iconos"
ICONOS_DIR.mkdir(parents=True, exist_ok=True)


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
discovered_match_players = deque(maxlen=60)
current_seeded_match_pair = ("", "")

ALLOWED_MEDIA_EXT = {".mp4", ".webm", ".ogg", ".mp3", ".wav", ".m4a"}
ALLOWED_BADGE_EXT = {".png", ".webp", ".jpg", ".jpeg", ".svg"}
BADGE_EXT_PRIORITY = {".png": 0, ".webp": 1, ".jpg": 2, ".jpeg": 3, ".svg": 4}


# Diccionario ligero en memoria (Costo $0, 0 llamadas a API, <0.05ms) para traducir nombres en español
# de selecciones nacionales y clubes europeos a los nombres en inglés/alemán de los archivos en app/escudos/
SPANISH_TEAM_SYNONYMS = {
    # Selecciones Nacionales (Español -> Inglés en footylogos)
    "espana": "spain",
    "seleccion espanola": "spain",
    "brasil": "brazil",
    "alemania": "germany",
    "inglaterra": "england",
    "francia": "france",
    "italia": "italy",
    "paises bajos": "netherlands",
    "holanda": "netherlands",
    "estados unidos": "usa",
    "eeuu": "usa",
    "ee uu": "usa",
    "corea del sur": "south korea",
    "surcorea": "south korea",
    "corea del norte": "north korea",
    "japon": "japan",
    "marruecos": "morocco",
    "suiza": "switzerland",
    "belgica": "belgium",
    "croacia": "croatia",
    "dinamarca": "denmark",
    "suecia": "sweden",
    "noruega": "norway",
    "polonia": "poland",
    "escocia": "scotland",
    "gales": "wales",
    "irlanda del norte": "northern ireland",
    "irlanda": "republic of ireland",
    "republica de irlanda": "republic of ireland",
    "turquia": "turkey",
    "grecia": "greece",
    "rusia": "russia",
    "ucrania": "ukraine",
    "rumania": "romania",
    "hungria": "hungary",
    "republica checa": "czech republic",
    "chequia": "czech republic",
    "eslovaquia": "slovakia",
    "eslovenia": "slovenia",
    "islandia": "iceland",
    "finlandia": "finland",
    "egipto": "egypt",
    "argelia": "algeria",
    "tunez": "tunisia",
    "camerun": "cameroon",
    "costa de marfil": "ivory coast",
    "sudafrica": "south africa",
    "arabia saudita": "saudi arabia",
    "arabia saudi": "saudi arabia",
    "emiratos arabes unidos": "united arab emirates",
    "emiratos arabes": "united arab emirates",
    "catar": "qatar",
    "nueva zelanda": "new zealand",
    "trinidad y tobago": "trinidad and tobago",
    "republica dominicana": "dominican republic",
    "puerto rico": "puerto rico",
    "costa rica": "costa rica",
    # Clubes con variación de idioma o siglas en los archivos SVG
    "psg": "paris saint germain",
    "paris sg": "paris saint germain",
    "bayern munich": "bayern munchen",
    "bayern": "bayern munchen",
    "bvb": "borussia dortmund",
    "ajax": "amsterdamsche ajax",
    "benfica": "sport lisboa benfica",
    "inter de milan": "inter milan",
    "inter": "inter milan",
    "milan": "ac milan",
    "psv": "philips vereniging",
    "psv eindhoven": "philips vereniging",
    "az alkmaar": "alkmaar zaanstreek",
    "colonia": "koln",
    "fc colonia": "koln",
    "friburgo": "freiburg",
    "maguncia": "mainz",
    "estrasburgo": "strasbourg",
    "marsella": "marseille",
    "olympique de marsella": "marseille",
    "lyon": "olympique lyonnais",
    "olympique de lyon": "olympique lyonnais",
    "niza": "nice",
    " napoles": "napoli",
    "sporting de lisboa": "sporting portugal",
    "sporting lisboa": "sporting portugal",
    "oporto": "porto",
    "fc oporto": "porto",
    "pumas": "universidad nacional",
    "pumas unam": "universidad nacional",
    "chivas": "deportivo guadalajara",
    "guadalajara": "deportivo guadalajara",
    "tigres": "tigres autonoma nuevo leon",
    "america": "club america",
    "aguilas del america": "club america",
    "nacional": "atletico nacional",
    "atletico nacional": "atletico nacional",
    "once caldas": "once caldas",
    "millonarios": "millonarios",
    "millonarios fc": "millonarios",
    "america de cali": "america de cali",
    "internacional de bogota": "internacional de bogota",
    "albeiro": "albeiro",
    "profe albeiro": "albeiro",
    "profesor albeiro": "albeiro",
    "albeiro caldas": "albeiro",
    "fc albeiro": "albeiro",
}


def _normalize_badge_tokens(raw_name: str, is_filename: bool = False) -> list[str]:
    """
    Quita tildes, prefijos numéricos ('01-', '15-'), versiones ('v2024'), sufijos ('national-team-logo-footylogos')
    y traduce nombres en español a inglés/alemán para encontrar siempre el escudo exacto en app/escudos/.
    """
    no_accents = "".join(
        c for c in unicodedata.normalize("NFKD", str(raw_name or ""))
        if not unicodedata.combining(c)
    ).lower()
    cleaned = re.sub(r"[^a-z0-9]+", " ", no_accents).strip()

    if not is_filename:
        # Quitar prefijos como "seleccion de ", "seleccion "
        cleaned = re.sub(r"^(seleccion\s+nacional\s+de\s+|seleccion\s+de\s+|seleccion\s+)", "", cleaned).strip()
        # Si el nombre completo está en el diccionario Español -> Inglés, reemplazarlo
        if cleaned in SPANISH_TEAM_SYNONYMS:
            cleaned = SPANISH_TEAM_SYNONYMS[cleaned]
        else:
            # También traducir palabras individuales conocidas (ej. 'munich' -> 'munchen', 'espana' -> 'spain')
            word_map = {
                "espana": "spain",
                "brasil": "brazil",
                "alemania": "germany",
                "inglaterra": "england",
                "francia": "france",
                "italia": "italy",
                "holanda": "netherlands",
                "japon": "japan",
                "marruecos": "morocco",
                "suiza": "switzerland",
                "belgica": "belgium",
                "croacia": "croatia",
                "dinamarca": "denmark",
                "suecia": "sweden",
                "noruega": "norway",
                "polonia": "poland",
                "escocia": "scotland",
                "gales": "wales",
                "turquia": "turkey",
                "rusia": "russia",
                "ucrania": "ukraine",
                "egipto": "egypt",
                "camerun": "cameroon",
                "munich": "munchen",
            }
            cleaned = " ".join(word_map.get(w, w) for w in cleaned.split())

    stopwords = {
        "fc", "cf", "rb", "sc", "ac", "cd", "ud", "rc", "rcd", "sv", "tsg", "fsv", "ogc", "losc", "aj", "us", "ss", "acf", "afc",
        "club", "clube", "de", "del", "do", "da", "la", "el", "los", "las", "e", "y", "m",
        "national", "team", "logo", "footylogos", "dutch", "football", "futbol", "futebol", "calcio", "association", "minor", "sad"
    }
    tokens = []
    for t in cleaned.split():
        if not t or t in stopwords:
            continue
        # Ignorar numeración inicial de archivos ('01', '15') y sufijos de versión ('v2024', 'v0000')
        if is_filename and (t.isdigit() or re.match(r"^v\d{4}$", t)):
            continue
        tokens.append(t)
    return tokens or cleaned.split()


def resolve_default_badge_file() -> Path:
    """Devuelve el escudo por defecto ('default.png', 'default.webp', 'default.jpg' o 'default.svg') de app/escudos/."""
    candidates = []
    for p in ESCUDOS_DIR.iterdir():
        if p.is_file() and p.suffix.lower() in ALLOWED_BADGE_EXT and p.stem.lower() in {"default", "escudo_default", "por_defecto"}:
            candidates.append(p)
    if candidates:
        candidates.sort(key=lambda x: BADGE_EXT_PRIORITY.get(x.suffix.lower(), 99))
        return candidates[0]
    return ESCUDOS_DIR / "default.svg"


def resolve_team_badge_file(team_name: str) -> Path:
    """
    Busca en solucion_proyecto/app/escudos/ el escudo que corresponda a `team_name`.
    Soporta nombres en español e inglés tanto para clubes como para selecciones nacionales.
    """
    clean_team = str(team_name or "").strip()
    if not clean_team or clean_team.lower() in {"equipo local", "equipo visitante", "local", "visitante", "transmisión oficial", "transmision oficial"}:
        return resolve_default_badge_file()

    team_tokens = _normalize_badge_tokens(clean_team, is_filename=False)
    if not team_tokens:
        return resolve_default_badge_file()

    team_set = set(team_tokens)
    team_joined = "_".join(team_tokens)
    best_match = None
    best_score = (-1, 0, 99)

    for p in ESCUDOS_DIR.iterdir():
        if not p.is_file() or p.suffix.lower() not in ALLOWED_BADGE_EXT:
            continue
        if p.stem.lower() in {"default", "escudo_default", "por_defecto"}:
            continue
        file_tokens = _normalize_badge_tokens(p.stem, is_filename=True)
        if not file_tokens:
            continue
        file_set = set(file_tokens)
        file_joined = "_".join(file_tokens)
        ext_prio = BADGE_EXT_PRIORITY.get(p.suffix.lower(), 99)
        common_tokens = team_set.intersection(file_set)

        # 1. Coincidencia exacta de todos los tokens limpios (ej. 'España' -> 'spain' == 'spain-national-team-logo-footylogos')
        if file_joined == team_joined or file_set == team_set:
            score = (4, len(common_tokens), -len(file_tokens), -ext_prio)
        # 2. Todos los tokens buscados están dentro del archivo (ej. 'Bayern Múnich' -> {'bayern', 'munchen'} en '15-FC-Bayern-Munchen-v2024')
        elif team_set.issubset(file_set):
            score = (3, len(common_tokens), -len(file_tokens), -ext_prio)
        # 3. Todos los tokens del archivo están dentro del nombre del equipo
        elif file_set.issubset(team_set):
            score = (2, len(common_tokens), -len(file_tokens), -ext_prio)
        # 4. Coincidencia parcial de tokens significativos (>= 4 letras)
        elif any(len(ft) >= 4 for ft in common_tokens):
            score = (1, len(common_tokens), -len(file_tokens), -ext_prio)
        else:
            continue

        if score > best_score:
            best_score = score
            best_match = p

    return best_match if best_match else resolve_default_badge_file()

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
simulated_peak_readers_vivo = 0
simulated_peak_readers_resumen = 0
simulated_peak_until = 0.0


def get_active_simulated_peak_counts() -> tuple[int, int, int]:
    """
    Devuelve (lectores_vivo_simulados, lectores_resumen_simulados, segundos_restantes)
    mientras esté activa la ventana de prueba de pico de 1,000 espectadores (HU-04).
    """
    global simulated_peak_readers_vivo, simulated_peak_readers_resumen, simulated_peak_until
    now = time.time()
    vivo_sim = 0
    res_sim = 0
    until_ts = simulated_peak_until

    if redis_client:
        try:
            r_until = float(redis_client.get("match:peak:until") or 0.0)
            if r_until > now:
                until_ts = r_until
                vivo_sim = int(redis_client.get("match:peak:vivo") or 0)
                res_sim = int(redis_client.get("match:peak:resumen") or 0)
        except Exception:
            pass

    if vivo_sim == 0 and res_sim == 0 and until_ts > now:
        vivo_sim = simulated_peak_readers_vivo
        res_sim = simulated_peak_readers_resumen

    if until_ts <= now or (vivo_sim + res_sim) <= 0:
        simulated_peak_readers_vivo = 0
        simulated_peak_readers_resumen = 0
        simulated_peak_until = 0.0
        return 0, 0, 0

    rem = max(1, int(round(until_ts - now)))
    # Pequeña fluctuación orgánica (±4 lectores) cada segundo para reflejar conexiones/reconexiones SSE en vivo
    jitter = (int(now * 2) % 9) - 4
    vivo_now = max(1, vivo_sim + jitter)
    return vivo_now, res_sim, rem


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
    global simulated_peak_readers_vivo, simulated_peak_readers_resumen, simulated_peak_until
    state["updated_at"] = datetime.now(timezone.utc).isoformat()
    local_match.update(state)
    if clear_events:
        local_events.clear()
        total_events_published = 0
        total_fanout_deliveries = 0
        simulated_peak_readers_vivo = 0
        simulated_peak_readers_resumen = 0
        simulated_peak_until = 0.0
    if redis_client:
        try:
            pipe = redis_client.pipeline()
            pipe.set("match:state", json.dumps(state))
            if clear_events:
                pipe.delete("match:events")
                pipe.set("match:metrics:events_published", 0)
                pipe.set("match:metrics:fanout_deliveries", 0)
                pipe.delete("match:peak:until", "match:peak:vivo", "match:peak:resumen")
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


def ensure_match_squad_seeded(home_team: str, away_team: str):
    """
    Pre-carga automáticamente (1 sola vez por partido) la plantilla de jugadores reales de los
    dos equipos en cancha (`home_team` y `away_team`) usando el conocimiento futbolístico de Groq LLM.
    Funciona para CUALQUIER partido del mundo (clubes o selecciones) y alimenta tanto el prompt
    de Whisper Large v3 Turbo como el corrector fonético dinámico.
    """
    global current_seeded_match_pair
    h = (home_team or "").strip()
    a = (away_team or "").strip()
    generic_names = {"", "equipo local", "equipo visitante", "local", "visitante", "transmisión oficial", "transmision oficial"}
    if h.lower() in generic_names and a.lower() in generic_names:
        return
    if (h.lower(), a.lower()) == current_seeded_match_pair and len(discovered_match_players) >= 10:
        return

    current_seeded_match_pair = (h.lower(), a.lower())
    groq_key = os.environ.get("GROQ_API_KEY", GROQ_API_KEY).strip()
    if not groq_key or not http_requests:
        return

    seed_prompt = (
        f"Lista los 30 jugadores más importantes (plantilla actual y reciente: arqueros, defensas, mediocampistas y delanteros) "
        f"de '{h}' y de '{a}'. Escribe sus nombres o apellidos exactamente como se les conoce en las transmisiones de fútbol "
        f"(ej. 'Manuel Neuer', 'Dayot Upamecano', 'Serge Gnabry', 'Jamal Musiala', 'Arda Güler', 'Kylian Mbappé'). "
        f"Responde UNICAMENTE con un objeto JSON válido con la clave: {{\"players\": [\"Jugador 1\", \"Jugador 2\", ...]}}"
    )
    for groq_model in ["openai/gpt-oss-120b", "openai/gpt-oss-20b"]:
        try:
            resp = http_requests.post(
                "https://api.groq.com/openai/v1/chat/completions",
                headers={"Authorization": f"Bearer {groq_key}", "Content-Type": "application/json"},
                json={
                    "model": groq_model,
                    "messages": [
                        {"role": "system", "content": "Eres una base de datos oficial de plantillas de fútbol mundial (UEFA / FIFA / Opta)."},
                        {"role": "user", "content": seed_prompt}
                    ],
                    "temperature": 0.0,
                    "max_tokens": 500,
                    "reasoning_effort": "low",
                    "response_format": {"type": "json_object"}
                },
                timeout=4.0
            )
            if resp.status_code == 200:
                data = json.loads(resp.json()["choices"][0]["message"]["content"].strip())
                players = data.get("players") or []
                if isinstance(players, list) and players:
                    remember_discovered_players([str(x) for x in players])
                    return
        except Exception:
            continue


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
    peak_vivo, peak_res, _ = get_active_simulated_peak_counts()
    current_readers_total = active_sse_clients["vivo"] + active_sse_clients["resumen"] + peak_vivo + peak_res
    fanout_increment = simulated_readers_override if simulated_readers_override > 0 else max(1, current_readers_total)
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
    (r"\b(?i:pamecano|upamekano|opamecano)\b", "Upamecano"),
    (r"\b(?i:noyer|noier|nuer)\b", "Neuer"),
    (r"\b(?i:naby|nabri|gnabri|nabry)\b", "Gnabry"),
    (r"\b(?i:chomeni|chuameni|tchouameni|choameni)\b", "Tchouaméni"),
    (r"\b(?i:camabinga|kamavinga)\b", "Camavinga"),
    (r"\b(?i:rudiguer|rudiger)\b", "Rüdiger"),
    (r"\b(?i:kimich|quimich)\b", "Kimmich"),
    (r"\b(?i:goretska|goretsca)\b", "Goretzka"),
    (r"\b(?i:chezni|szczesny)\b", "Szczęsny"),
    (r"\b(?i:undogan|gundogan)\b", "Gündoğan"),
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
    """
    Corrige nombres de jugadores mal transcritos por la velocidad del relator o el ruido de estadio:
    1. Aplica reglas fonéticas directas.
    2. Aplica similitud fonética/ortográfica dinámica (`difflib`) contra los apellidos reales
       de los jugadores de los 2 equipos del partido actual (`discovered_match_players`),
       para corregir automáticamente elisiones como 'Pamecano' -> 'Upamecano' en cualquier partido.
    """
    cleaned = raw_text.strip()
    for pattern, replacement in FOOTBALL_PHONETIC_FIXES:
        cleaned = re.sub(pattern, replacement, cleaned)

    if not discovered_match_players:
        return cleaned

    # Construir mapa de apellidos/nombres de la plantilla activa del partido
    surname_map = {}
    for full_name in discovered_match_players:
        parts = [p.strip(".,") for p in full_name.split() if len(p.strip(".,")) >= 5]
        for part in parts:
            norm_part = "".join(
                c for c in unicodedata.normalize("NFKD", part) if not unicodedata.combining(c)
            ).lower()
            surname_map[norm_part] = part

    if not surname_map:
        return cleaned

    common_spanish_words = {
        "partido", "equipo", "pelota", "balon", "arquero", "portero", "defensa", "ataque", "contra",
        "minuto", "segundo", "tiempo", "cambio", "tarjeta", "amarilla", "arbitro", "cancha", "jugada",
        "remate", "disparo", "centro", "corner", "tiro", "esquina", "frente", "puerta", "arco", "area",
        "derecha", "izquierda", "mediocampo", "lateral", "central", "delantero", "volante", "cabezazo",
        "primero", "segundo", "tercero", "cuarto", "victoria", "empate", "derrota", "ventaja", "marcador"
    }

    def _replace_close_token(match_obj):
        word = match_obj.group(0)
        if len(word) < 5:
            return word
        norm_w = "".join(
            c for c in unicodedata.normalize("NFKD", word) if not unicodedata.combining(c)
        ).lower()
        if norm_w in common_spanish_words or norm_w in surname_map:
            return surname_map.get(norm_w, word)
        # Si empieza con mayúscula (Whisper la detectó como nombre propio) o es muy similar a un apellido en cancha
        best_surname = None
        best_ratio = 0.0
        for norm_s, proper_s in surname_map.items():
            # Caso 1: Elisión de primera letra vocálica/muda (ej. 'pamecano' vs 'upamecano', 'nabry' vs 'gnabry')
            if len(norm_s) >= 6 and norm_s[1:] == norm_w:
                return proper_s
            ratio = difflib.SequenceMatcher(None, norm_w, norm_s).ratio()
            threshold = 0.82 if word[0].isupper() else 0.87
            if ratio >= threshold and ratio > best_ratio:
                best_ratio = ratio
                best_surname = proper_s
        return best_surname if best_surname else word

    return re.sub(r"\b[A-Za-zÁÉÍÓÚÜÑáéíóúüñ]{5,}\b", _replace_close_token, cleaned)


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

        # Pre-cargar automáticamente la plantilla de los dos equipos activos (funciona para cualquier partido)
        ensure_match_squad_seeded(home_t, away_t)

        # Construir lista dinámica enfocada en los jugadores de este partido para no saturar el límite de 224 tokens de Whisper
        learned_roster = ", ".join(list(discovered_match_players)[:36])
        base_vocab = (
            "Manuel Neuer, Dayot Upamecano, Joshua Kimmich, Jamal Musiala, Leroy Sané, Serge Gnabry, Harry Kane, Michael Olise, "
            "Andriy Lunin, Thibaut Courtois, Dani Carvajal, Antonio Rüdiger, Aurélien Tchouaméni, Eduardo Camavinga, Toni Kroos, "
            "Federico Valverde, Jude Bellingham, Arda Güler, Rodrygo, Vinícius Jr., Kylian Mbappé, "
            "Erling Haaland, Nico O'Reilly, Rayan Cherki, Phil Foden, Kevin De Bruyne, Josko Gvardiol, Loïs Openda, Xavi Simons"
        )
        roster_prompt_str = learned_roster if len(discovered_match_players) >= 8 else f"{learned_roster}, {base_vocab}".strip(", ")

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
    a Groq LLM (openai/gpt-oss-120b / qwen3.8-27b) para estructurar el JSON deportivo sin adivinar goleadores
    y reconstruyendo fonéticamente cualquier apellido distorsionado por el audio.
    """
    home_t = str(current_state.get("home_team", "Equipo Local"))
    away_t = str(current_state.get("away_team", "Equipo Visitante"))
    ensure_match_squad_seeded(home_t, away_t)

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
        "5. RECONSTRUCCIÓN FONÉTICA INTELIGENTE DE JUGADORES (MUY IMPORTANTE): La transcripción proviene de audio rápido en español y a menudo escribe apellidos extranjeros "
        "como suenan fonéticamente o comiéndose la primera letra (ej. 'Pamecano' por 'Upamecano', 'Noyer' por 'Neuer', 'Naby/Nabri' por 'Gnabry', 'Chomeni' por 'Tchouaméni', 'Chezni' por 'Szczęsny'). "
        f"Usa tu conocimiento de las plantillas reales de '{home_t}' y '{away_t}' (más la lista de jugadores identificados) para reconstruir y corregir SIEMPRE cualquier apellido que suene parecido, "
        "tanto en 'player' como en 'description', en 'detected_players' y en 'corrected_transcript'.\n"
        "Responde UNICAMENTE con un objeto JSON válido con estas claves:\n"
        "{\n"
        '  "type": "GOAL" | "GOAL_CONFIRMATION" | "PENALTY" | "RED_CARD" | "YELLOW_CARD" | "SUBSTITUTION" | "MATCH_START" | "MATCH_END" | "COMMENT",\n'
        '  "team": "HOME" | "AWAY" | "NEUTRAL",\n'
        '  "home_team": "Nombre del equipo local",\n'
        '  "away_team": "Nombre del equipo visitante",\n'
        '  "home_score_override": numero_entero_goles_local_actualizado,\n'
        '  "away_score_override": numero_entero_goles_visitante_actualizado,\n'
        '  "minute": numero_entero_del_minuto,\n'
        '  "player": "Nombre confirmado y bien escrito del jugador protagonista o Autor por confirmar",\n'
        '  "detected_players": ["Jugador 1 bien escrito", "Jugador 2 bien escrito"],\n'
        '  "corrected_transcript": "Transcripción original del relator pero con todos los nombres de futbolistas y clubes corregidos ortográficamente",\n'
        '  "description": "Comentario periodístico profesional con todos los nombres de jugadores perfectamente escritos"\n'
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
        for groq_model in ["openai/gpt-oss-120b", "openai/gpt-oss-20b"]:
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
                        "max_tokens": 500,
                        "reasoning_effort": "low",
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
# AUTENTICACIÓN DE PRENSA Y BLOQUEO DE CABINA DE SESIÓN ÚNICA (1 PERIODISTA ACTIVO)
# ==============================================================================
JOURNALIST_SESSION_TTL_SEC = 45
journalist_session_lock = threading.Lock()
local_journalist_session = {
    "session_id": "",
    "ip": "",
    "expires_at": 0.0
}


def get_active_journalist_session() -> dict | None:
    now = time.time()
    if redis_client:
        try:
            raw = redis_client.get("match:journalist_session")
            if raw:
                data = json.loads(raw)
                if float(data.get("expires_at", 0)) > now:
                    return data
        except Exception:
            pass
    with journalist_session_lock:
        if local_journalist_session["session_id"] and local_journalist_session["expires_at"] > now:
            return dict(local_journalist_session)
    return None


def set_active_journalist_session(session_id: str, client_ip: str, ttl_sec: int = JOURNALIST_SESSION_TTL_SEC) -> dict:
    expires_at = time.time() + ttl_sec
    payload = {
        "session_id": session_id,
        "ip": client_ip,
        "expires_at": expires_at,
        "updated_at": datetime.now(timezone.utc).isoformat()
    }
    with journalist_session_lock:
        local_journalist_session["session_id"] = session_id
        local_journalist_session["ip"] = client_ip
        local_journalist_session["expires_at"] = expires_at
    if redis_client:
        try:
            redis_client.setex("match:journalist_session", ttl_sec, json.dumps(payload))
        except Exception:
            pass
    return payload


def clear_active_journalist_session():
    with journalist_session_lock:
        local_journalist_session["session_id"] = ""
        local_journalist_session["ip"] = ""
        local_journalist_session["expires_at"] = 0.0
    if redis_client:
        try:
            redis_client.delete("match:journalist_session")
        except Exception:
            pass


def verify_journalist_request() -> tuple[bool, str, int]:
    """
    Verifica la credencial del periodista (`X-Journalist-Token`) y, si viene desde la consola web
    con `X-Journalist-Session`, garantiza que ningún otro navegador haya tomado el control de la cabina.
    """
    json_body = request.get_json(silent=True) if request.is_json else {}
    json_body = json_body or {}
    token = (
        request.headers.get("X-Journalist-Token")
        or json_body.get("token")
        or request.form.get("token")
        or ""
    )
    if token != JOURNALIST_TOKEN:
        return False, "No autorizado. Credencial de periodista inválida.", 401

    session_id = (
        request.headers.get("X-Journalist-Session")
        or json_body.get("session_id")
        or request.form.get("session_id")
        or ""
    ).strip()
    if session_id:
        active = get_active_journalist_session()
        client_ip = request.headers.get("X-Real-IP") or request.remote_addr or "0.0.0.0"
        if active and active.get("session_id") != session_id:
            return False, "Otro periodista tomó el control activo de la cabina.", 403
        set_active_journalist_session(session_id, client_ip)
    return True, "", 200


@app.get("/api/auth/journalist-status")
def api_journalist_auth_status():
    """Verifica el estado de la sesión del periodista y si la cabina ya está ocupada."""
    session_id = (request.headers.get("X-Journalist-Session") or request.args.get("session_id") or "").strip()
    token = (request.headers.get("X-Journalist-Token") or "").strip()
    active = get_active_journalist_session()
    client_ip = request.headers.get("X-Real-IP") or request.remote_addr or "0.0.0.0"

    if active:
        is_owner = bool(session_id and active.get("session_id") == session_id and token == JOURNALIST_TOKEN)
        if is_owner:
            set_active_journalist_session(session_id, client_ip)
        return jsonify(
            authenticated=is_owner,
            cabin_occupied=not is_owner,
            active_ip=active.get("ip", "activa")
        )

    return jsonify(
        authenticated=False,
        cabin_occupied=False,
        active_ip=""
    )


@app.post("/api/auth/journalist-login")
def api_journalist_login():
    """
    Inicia sesión en la Cabina del Periodista.
    Garantiza sesión única activa (1 solo periodista transmitiendo a la vez).
    """
    body = request.get_json(silent=True) or {}
    password = str(body.get("password") or body.get("token") or "").strip()
    force_takeover = bool(body.get("force_takeover", False))
    existing_session_id = str(body.get("session_id") or request.headers.get("X-Journalist-Session") or "").strip()

    if password != JOURNALIST_TOKEN:
        return jsonify(error="Clave de acceso incorrecta. Verifica tu credencial de prensa."), 401

    active = get_active_journalist_session()
    client_ip = request.headers.get("X-Real-IP") or request.remote_addr or "0.0.0.0"

    if active and active.get("session_id") != existing_session_id and not force_takeover:
        return jsonify(
            status="occupied",
            cabin_occupied=True,
            active_ip=active.get("ip", "activa"),
            error="Ya hay un periodista con la cabina abierta en este momento. Pulsa nuevamente para tomar el control exclusivo."
        ), 409

    new_session_id = existing_session_id or uuid.uuid4().hex
    set_active_journalist_session(new_session_id, client_ip)
    return jsonify(
        status="authenticated",
        authenticated=True,
        session_id=new_session_id,
        token=JOURNALIST_TOKEN
    ), 200


@app.post("/api/auth/journalist-logout")
def api_journalist_logout():
    """Cierra la sesión activa de la Cabina del Periodista y libera el candado."""
    session_id = (request.headers.get("X-Journalist-Session") or (request.get_json(silent=True) or {}).get("session_id") or "").strip()
    active = get_active_journalist_session()
    if not active or active.get("session_id") == session_id:
        clear_active_journalist_session()
    return jsonify(status="logged_out", cabin_occupied=False), 200


# ==============================================================================
# VISTAS SEPARADAS: PORTAL PÚBLICO DE AFICIONADOS vs. CABINA DEL PERIODISTA
# ==============================================================================
@app.get("/favicon.ico")
def favicon():
    return api_ui_icon("logo")


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
# ENDPOINTS DE ARCHIVOS MULTIMEDIA, CUOTA DE DISCO Y EXTRACCIÓN DE VOZ DEL VIDEO
# ==============================================================================
MAX_MEDIA_STORAGE_MB = float(os.environ.get("MAX_MEDIA_STORAGE_MB", "1000.0"))


def get_media_storage_stats() -> dict:
    """Calcula el espacio ocupado en app/media y el límite seguro disponible (máx 1000 MB por defecto)."""
    used_bytes = 0
    file_count = 0
    for p in MEDIA_DIR.iterdir():
        if p.is_file() and p.suffix.lower() in ALLOWED_MEDIA_EXT:
            used_bytes += p.stat().st_size
            file_count += 1
    used_mb = round(used_bytes / (1024 * 1024), 2)

    try:
        disk = shutil.disk_usage(MEDIA_DIR)
        # Dejar siempre al menos 1,000 MB libres para el SO, Docker y Jenkins
        os_safe_free_mb = max(0.0, (disk.free / (1024 * 1024)) - 1000.0)
        limit_mb = round(min(MAX_MEDIA_STORAGE_MB, used_mb + os_safe_free_mb), 1)
        if limit_mb < 100.0:
            limit_mb = MAX_MEDIA_STORAGE_MB
    except Exception:
        limit_mb = MAX_MEDIA_STORAGE_MB

    remaining_mb = round(max(0.0, limit_mb - used_mb), 2)
    percent_used = round(min(100.0, (used_mb / limit_mb) * 100.0), 1) if limit_mb > 0 else 100.0
    return {
        "used_mb": used_mb,
        "limit_mb": limit_mb,
        "remaining_mb": remaining_mb,
        "percent_used": percent_used,
        "file_count": file_count
    }


@app.get("/api/media/list")
def api_media_list():
    """Lista los videos/audios reales colocados en solucion_proyecto/app/media/ y el espacio disponible."""
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
        storage=get_media_storage_stats(),
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

    stats = get_media_storage_stats()
    existing_mb = round(dest.stat().st_size / (1024 * 1024), 2) if dest.exists() else 0.0
    available_for_upload_mb = round(stats["remaining_mb"] + existing_mb, 2)

    content_len = request.content_length or 0
    incoming_mb = round(content_len / (1024 * 1024), 2)
    if incoming_mb > 0 and incoming_mb > available_for_upload_mb:
        return jsonify(
            error=(
                f"Espacio insuficiente: el video pesa {incoming_mb} MB y solo quedan "
                f"{available_for_upload_mb} MB disponibles (límite {stats['limit_mb']} MB). "
                "Elimina un video anterior para poder subir este."
            ),
            storage=stats
        ), 413

    f.save(dest)
    saved_mb = round(dest.stat().st_size / (1024 * 1024), 2)
    if saved_mb > available_for_upload_mb:
        dest.unlink(missing_ok=True)
        return jsonify(
            error=(
                f"Espacio insuficiente: el video pesa {saved_mb} MB y solo quedan "
                f"{available_for_upload_mb} MB disponibles (límite {stats['limit_mb']} MB). "
                "Elimina un video anterior para poder subir este."
            ),
            storage=get_media_storage_stats()
        ), 413

    inferred = infer_teams_from_filename(f.filename)
    return jsonify(
        status="uploaded",
        filename=safe_name,
        url=f"/media/{safe_name}",
        size_mb=saved_mb,
        inferred_home=inferred[0] if inferred else "",
        inferred_away=inferred[1] if inferred else "",
        saved_in=str(dest),
        storage=get_media_storage_stats()
    ), 201


@app.post("/api/media/delete")
@app.delete("/api/media/delete")
def api_media_delete():
    """Elimina un video/audio de app/media/ para liberar espacio en el servidor."""
    ok, err_msg, code = verify_journalist_request()
    if not ok:
        return jsonify(error=err_msg), code

    body = request.get_json(silent=True) or {}
    raw_filename = str(body.get("filename") or request.args.get("filename") or "").strip()
    if not raw_filename:
        return jsonify(error="Debes seleccionar un archivo para eliminar."), 400

    # Si viene como URL '/media/archivo.mp4', extraer el nombre
    if raw_filename.startswith("/media/"):
        raw_filename = raw_filename[len("/media/"):]

    target = resolve_media_file(raw_filename)
    if not target or not target.exists():
        return jsonify(error=f"El archivo '{raw_filename}' no existe."), 404

    freed_mb = round(target.stat().st_size / (1024 * 1024), 2)
    deleted_name = target.name
    target.unlink(missing_ok=True)

    return jsonify(
        status="deleted",
        deleted=deleted_name,
        freed_mb=freed_mb,
        storage=get_media_storage_stats()
    ), 200


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


# ==============================================================================
# BODEGA DE ESCUDOS DE EQUIPOS (solucion_proyecto/app/escudos/ + default)
# ==============================================================================
@app.get("/escudos/<path:filename>")
def serve_escudo_file(filename: str):
    return send_from_directory(ESCUDOS_DIR, filename)


@app.get("/iconos/<path:filename>")
def serve_icono_file(filename: str):
    return send_from_directory(ICONOS_DIR, filename)


@app.get("/api/icon/<path:icon_name>")
def api_ui_icon(icon_name: str):
    """
    Sirve un ícono de la interfaz desde `solucion_proyecto/app/iconos/`.
    Da prioridad a imágenes subidas por el desarrollador (.png, .webp, .jpg, .jpeg)
    y si no existen usa el ícono vectorial .svg incluido.
    """
    raw = Path(icon_name).stem.lower().strip()
    alias_map = {
        "gol": ["balon", "gol", "goal"],
        "goal": ["balon", "gol", "goal"],
        "balon": ["balon", "gol", "goal"],
        "yellow_card": ["amarilla", "tarjeta_amarilla", "yellow"],
        "amarilla": ["amarilla", "tarjeta_amarilla", "yellow"],
        "red_card": ["roja", "tarjeta_roja", "red"],
        "roja": ["roja", "tarjeta_roja", "red"],
        "substitution": ["cambio", "sustitucion", "sub"],
        "cambio": ["cambio", "sustitucion", "sub"],
        "penalty": ["penal", "var", "penalty"],
        "penal": ["penal", "var", "penalty"],
        "comment": ["comentario", "minuto", "comment"],
        "match_start": ["comentario", "inicio", "balon"],
        "comentario": ["comentario", "minuto", "comment"],
        "microfono": ["microfono", "mic", "voz"],
        "logo": ["logo", "icono_pagina", "brand"],
    }
    candidates = alias_map.get(raw, [raw])
    for stem in candidates:
        for ext in [".png", ".webp", ".jpg", ".jpeg", ".svg"]:
            candidate_path = ICONOS_DIR / f"{stem}{ext}"
            if candidate_path.exists():
                resp = send_from_directory(ICONOS_DIR, candidate_path.name)
                resp.headers["Cache-Control"] = "public, max-age=3600"
                return resp
    fallback = ICONOS_DIR / "balon.svg"
    if fallback.exists():
        return send_from_directory(ICONOS_DIR, fallback.name)
    return jsonify(error="Icono no encontrado"), 404


@app.get("/api/badge")
@app.get("/api/badge/<path:team_name>")
def api_team_badge(team_name: str = ""):
    """
    Devuelve la imagen del escudo del equipo buscándola en `solucion_proyecto/app/escudos/`.
    Si el equipo no existe en la bodega, sirve automáticamente `default.png` / `default.svg`.
    """
    q_team = request.args.get("team", team_name)
    badge_path = resolve_team_badge_file(q_team)
    if badge_path and badge_path.exists():
        resp = send_from_directory(ESCUDOS_DIR, badge_path.name)
        resp.headers["Cache-Control"] = "public, max-age=3600"
        return resp
    return jsonify(error="Escudo default no encontrado"), 404


@app.get("/api/escudos/list")
def api_escudos_list():
    """Lista todos los escudos disponibles actualmente en `solucion_proyecto/app/escudos/`."""
    items = []
    for p in sorted(ESCUDOS_DIR.iterdir()):
        if p.is_file() and p.suffix.lower() in ALLOWED_BADGE_EXT:
            items.append({
                "filename": p.name,
                "url": f"/escudos/{p.name}",
                "is_default": p.stem.lower() in {"default", "escudo_default", "por_defecto"},
                "size_kb": round(p.stat().st_size / 1024, 1)
            })
    return jsonify(escudos_dir=str(ESCUDOS_DIR), count=len(items), badges=items)


@app.post("/api/escudos/upload")
def api_escudos_upload():
    """Permite subir un escudo (.png, .webp, .jpg, .svg) directamente a `solucion_proyecto/app/escudos/`."""
    if "file" not in request.files:
        return jsonify(error="No se envió imagen de escudo"), 400
    f = request.files["file"]
    if not f.filename:
        return jsonify(error="Nombre de archivo vacío"), 400
    ext = Path(f.filename).suffix.lower()
    if ext not in ALLOWED_BADGE_EXT:
        return jsonify(error=f"Formato no soportado ({ext}). Usa PNG, WEBP, JPG o SVG."), 400

    custom_name = (request.form.get("team_name") or "").strip()
    if custom_name:
        safe_stem = re.sub(r"[^a-zA-Z0-9_-]+", "_", custom_name.lower()).strip("_")
        safe_name = f"{safe_stem}{ext}"
    else:
        safe_name = secure_filename(f.filename)

    dest = ESCUDOS_DIR / safe_name
    f.save(dest)
    return jsonify(
        status="uploaded",
        filename=safe_name,
        url=f"/escudos/{safe_name}",
        saved_in=str(dest)
    ), 201


@app.post("/api/ai/transcribe-mic")
def api_transcribe_microphone_audio():
    """
    Recibe el audio grabado por el micrófono (desde PC o desde el celular por HTTP/Wi-Fi),
    lo convierte a WAV 16kHz con FFmpeg, lo transcribe con Whisper Large v3 Turbo (Groq)
    usando el vocabulario del partido y publica la jugada en el Portal de Espectadores.
    """
    ok, err_msg, code = verify_journalist_request()
    if not ok:
        return jsonify(error=err_msg), code

    if "file" not in request.files:
        return jsonify(error="No se recibió audio del micrófono"), 400
    audio_file = request.files["file"]
    raw_bytes = audio_file.read()
    if not raw_bytes or len(raw_bytes) < 500:
        return jsonify(error="Audio demasiado corto o vacío"), 400

    try:
        cmd = [
            "ffmpeg", "-y",
            "-i", "pipe:0",
            "-vn", "-ac", "1", "-ar", "16000", "-f", "wav", "pipe:1"
        ]
        proc = subprocess.run(cmd, input=raw_bytes, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=10)
        wav_bytes = proc.stdout if (proc.stdout and len(proc.stdout) > 1000) else raw_bytes
    except Exception:
        wav_bytes = raw_bytes

    current_state = get_match_state()
    home_t = current_state.get("home_team", "Equipo Local")
    away_t = current_state.get("away_team", "Equipo Visitante")
    groq_key = os.environ.get("GROQ_API_KEY", GROQ_API_KEY).strip()

    learned_roster = ", ".join(list(discovered_match_players))
    base_vocab = (
        "Erling Haaland, Nico O'Reilly, Rayan Cherki, Phil Foden, Kevin De Bruyne, Rodri, Gvardiol, "
        "Loïs Openda, Xavi Simons, Benjamin Šeško, Antonio Nusa, Dani Olmo, "
        "Manuel Neuer, Upamecano, Kimmich, Jamal Musiala, Leroy Sané, Harry Kane, Luis Díaz, Gnabry, Michael Olise, "
        "Lunin, Carvajal, Rüdiger, Toni Kroos, Federico Valverde, Jude Bellingham, Arda Güler, Rodrygo, Vinícius Jr., Kylian Mbappé, "
        "Mohamed Salah, Virgil van Dijk, Mac Allister, Cole Palmer, Moisés Caicedo, Enzo Fernández"
    )
    roster_prompt_str = f"{learned_roster}, {base_vocab}" if learned_roster else base_vocab

    transcript = ""
    stt_engine = "none"

    if groq_key and http_requests:
        try:
            football_context_prompt = (
                f"Relato deportivo de fútbol en vivo en español. Partido entre {home_t} y {away_t}. "
                f"Jugadores: {roster_prompt_str}."
            )
            resp = http_requests.post(
                "https://api.groq.com/openai/v1/audio/transcriptions",
                headers={"Authorization": f"Bearer {groq_key}"},
                files={"file": ("mic.wav", wav_bytes, "audio/wav")},
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
                    transcript = apply_football_phonetics(whisper_text)
                    stt_engine = "Whisper-Large-v3-Turbo (Groq Mic)"
        except Exception:
            pass

    if not transcript and sr:
        try:
            recognizer = sr.Recognizer()
            with sr.AudioFile(io.BytesIO(wav_bytes)) as source:
                audio_data = recognizer.record(source)
            text = recognizer.recognize_google(audio_data, language="es-ES")
            transcript = apply_football_phonetics(text)
            stt_engine = "SpeechRecognition+FootballDict"
        except Exception:
            pass

    if not transcript:
        return jsonify(error="No se detectó voz clara en la grabación. Intenta hablar más cerca del micrófono."), 200

    ai_event = interpret_narrator_with_openrouter(transcript, current_state)
    ai_event["stt_engine"] = stt_engine
    clean_transcript_out = ai_event.get("corrected_transcript") or apply_football_phonetics(transcript)
    result = publish_event_fanout(ai_event)
    return jsonify(
        status="ai_published",
        stt_engine=stt_engine,
        transcript_received=clean_transcript_out,
        ai_interpretation=ai_event,
        **result
    ), 201


@app.post("/api/ai/process-video-chunk")
def api_process_video_chunk():
    """
    Recibe el nombre del video en reproducción y el segundo actual (`start_sec`).
    Extrae el audio real del video con FFmpeg, lo transcribe a texto con SpeechRecognition
    y se lo envía a OpenRouter para publicar automáticamente la jugada en el Portal de Espectadores.
    """
    ok, err_msg, code = verify_journalist_request()
    if not ok:
        return jsonify(error=err_msg), code

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
    clean_transcript_out = ai_event.get("corrected_transcript") or apply_football_phonetics(transcript)

    # 3. Publicar automáticamente al Portal de Espectadores (SNS -> SQS -> Redis -> SSE)
    result = publish_event_fanout(ai_event)
    return jsonify(
        status="ai_published",
        chunk_start_sec=round(start_sec, 1),
        stt_engine=stt_engine,
        transcript_received=clean_transcript_out,
        ai_interpretation=ai_event,
        **result
    ), 201


@app.post("/api/ai/narrate")
def api_ai_narrate():
    """
    Opción 2: Recibe una frase del micrófono en vivo o escrita por el comentarista,
    la envía a OpenRouter y publica la jugada en el Portal de Espectadores.
    """
    ok, err_msg, code = verify_journalist_request()
    if not ok:
        return jsonify(error=err_msg), code

    body = request.get_json(silent=True) or {}
    transcript = str(body.get("transcript", "")).strip()
    if not transcript:
        return jsonify(error="Se requiere el texto/transcripción del comentarista."), 400

    video_minute = body.get("video_minute")
    current_state = get_match_state()

    ai_event = interpret_narrator_with_openrouter(transcript, current_state, video_minute)
    clean_transcript_out = ai_event.get("corrected_transcript") or apply_football_phonetics(transcript)
    result = publish_event_fanout(ai_event)
    return jsonify(
        status="ai_published",
        transcript_received=clean_transcript_out,
        ai_interpretation=ai_event,
        **result
    ), 201


@app.post("/api/match/setup")
def api_match_setup():
    """Configura equipos o reinicia el tablero completamente en blanco (0-0, 0 eventos)."""
    global current_seeded_match_pair
    ok, err_msg, code = verify_journalist_request()
    if not ok:
        return jsonify(error=err_msg), code

    body = request.get_json(silent=True) or {}
    if body.get("blank_reset"):
        recent_transcripts_history.clear()
        discovered_match_players.clear()
        current_seeded_match_pair = ("", "")
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
        current_seeded_match_pair = ("", "")
        state["home_score"] = 0
        state["away_score"] = 0
        state["minute"] = 0
        state["status"] = "EN VIVO · 1T"
    if body.get("clear_events"):
        recent_transcripts_history.clear()
        discovered_match_players.clear()
        current_seeded_match_pair = ("", "")

    save_match_state(state, clear_events=bool(body.get("clear_events", False)))
    threading.Thread(
        target=ensure_match_squad_seeded,
        args=(state.get("home_team", ""), state.get("away_team", "")),
        daemon=True
    ).start()
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
    ok, err_msg, code = verify_journalist_request()
    if not ok:
        return jsonify(error=err_msg), code

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


SSE_VIEWER_TTL_SEC = 7.0
local_active_viewers = {"vivo": {}, "resumen": {}}


def register_sse_viewer_heartbeat(channel: str, viewer_id: str):
    now = time.time()
    other_ch = "resumen" if channel == "vivo" else "vivo"
    with metrics_lock:
        local_active_viewers[other_ch].pop(viewer_id, None)
        local_active_viewers[channel][viewer_id] = now
    if redis_client:
        try:
            pipe = redis_client.pipeline()
            pipe.zrem(f"match:sse_zset:{other_ch}", viewer_id)
            pipe.zadd(f"match:sse_zset:{channel}", {viewer_id: now})
            pipe.expire(f"match:sse_zset:{channel}", 30)
            pipe.execute()
        except Exception:
            pass


def unregister_sse_viewer(channel: str, viewer_id: str):
    with metrics_lock:
        local_active_viewers[channel].pop(viewer_id, None)
    if redis_client:
        try:
            redis_client.zrem(f"match:sse_zset:{channel}", viewer_id)
        except Exception:
            pass


def get_real_sse_counts() -> tuple[int, int]:
    """Devuelve el conteo exacto de espectadores activos limpiando conexiones expiradas (>7s)."""
    cutoff = time.time() - SSE_VIEWER_TTL_SEC
    with metrics_lock:
        for ch in ("vivo", "resumen"):
            stale = [vid for vid, ts in local_active_viewers[ch].items() if ts < cutoff]
            for vid in stale:
                local_active_viewers[ch].pop(vid, None)
        vivo_cnt = len(local_active_viewers["vivo"])
        res_cnt = len(local_active_viewers["resumen"])

    if redis_client:
        try:
            pipe = redis_client.pipeline()
            pipe.zremrangebyscore("match:sse_zset:vivo", "-inf", cutoff)
            pipe.zremrangebyscore("match:sse_zset:resumen", "-inf", cutoff)
            pipe.zcard("match:sse_zset:vivo")
            pipe.zcard("match:sse_zset:resumen")
            _, _, r_vivo, r_res = pipe.execute()
            vivo_cnt = max(vivo_cnt, int(r_vivo or 0))
            res_cnt = max(res_cnt, int(r_res or 0))
        except Exception:
            pass

    active_sse_clients["vivo"] = vivo_cnt
    active_sse_clients["resumen"] = res_cnt
    return vivo_cnt, res_cnt


@app.get("/api/stream/<channel>")
def api_stream(channel: str):
    channel = "resumen" if channel.lower() == "resumen" else "vivo"
    viewer_id = (request.args.get("vid") or "").strip() or uuid.uuid4().hex

    def event_stream():
        register_sse_viewer_heartbeat(channel, viewer_id)
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
                if sent:
                    register_sse_viewer_heartbeat(channel, viewer_id)
                elif (now - last_heartbeat) >= 3.0:
                    register_sse_viewer_heartbeat(channel, viewer_id)
                    hb = json.dumps({"ts": now, "node": HOSTNAME, "channel": channel})
                    yield f"event: heartbeat\ndata: {hb}\n\n"
                    last_heartbeat = now
        except GeneratorExit:
            pass
        finally:
            unregister_sse_viewer(channel, viewer_id)
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
    sse_vivo, sse_res = get_real_sse_counts()

    if redis_client:
        try:
            ev_pub = int(redis_client.get("match:metrics:events_published") or ev_pub)
            fanout_del = int(redis_client.get("match:metrics:fanout_deliveries") or fanout_del)
        except Exception:
            pass

    peak_vivo, peak_res, peak_remaining_sec = get_active_simulated_peak_counts()
    total_vivo = sse_vivo + peak_vivo
    total_res = sse_res + peak_res

    return jsonify(
        node=HOSTNAME,
        service_role=SERVICE_ROLE,
        active_sse_vivo=total_vivo,
        active_sse_resumen=total_res,
        total_active_readers=total_vivo + total_res,
        peak_simulation_active=(peak_remaining_sec > 0),
        peak_remaining_sec=peak_remaining_sec,
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


def _sustain_peak_traffic_worker(readers_count: int, end_timestamp: float):
    """
    Hilo en segundo plano que mantiene activa la carga de lecturas en caché (HU-03 / HU-04)
    durante la ventana de simulación (45s) sin inventar goles ni ensuciar el marcador del partido.
    """
    global total_fanout_deliveries
    while time.time() < end_timestamp and simulated_peak_until >= end_timestamp:
        t_start = time.perf_counter()
        _ = get_match_state()
        _ = get_all_events(limit=30)
        sample_ms = round((time.perf_counter() - t_start) * 1000, 2)
        batch_deliveries = max(50, readers_count // 10)
        with metrics_lock:
            latency_samples.append(sample_ms)
            total_fanout_deliveries += batch_deliveries
        if redis_client:
            try:
                redis_client.incrby("match:metrics:fanout_deliveries", batch_deliveries)
            except Exception:
                pass
        time.sleep(2.5)


@app.post("/api/simulate-peak")
def api_simulate_peak():
    """
    Simula un pico real de 1,000 espectadores concurrentes (HU-04 + HU-03) durante 45 segundos:
    - NO inventa goles falsos ni altera el marcador del partido en curso.
    - Conecta 850 lectores en el canal 'vivo' y 150 lectores en el canal 'resumen' (entré tarde).
    - Ejecuta 1,000 lecturas reales de estado/resumen desde caché midiendo la latencia p50/p95/p99.
    """
    global total_fanout_deliveries
    global simulated_peak_readers_vivo, simulated_peak_readers_resumen, simulated_peak_until

    body = request.get_json(silent=True) or {}
    simulated_readers = max(10, int(body.get("readers", 1000)))
    duration_sec = max(15, min(120, int(body.get("duration_sec", 45))))

    vivo_readers = int(round(simulated_readers * 0.85))
    resumen_readers = simulated_readers - vivo_readers
    end_ts = time.time() + duration_sec

    simulated_peak_readers_vivo = vivo_readers
    simulated_peak_readers_resumen = resumen_readers
    simulated_peak_until = end_ts

    if redis_client:
        try:
            pipe = redis_client.pipeline()
            pipe.set("match:peak:until", str(end_ts), ex=duration_sec + 5)
            pipe.set("match:peak:vivo", vivo_readers, ex=duration_sec + 5)
            pipe.set("match:peak:resumen", resumen_readers, ex=duration_sec + 5)
            pipe.incrby("match:metrics:fanout_deliveries", simulated_readers)
            pipe.execute()
        except Exception:
            pass

    # Ejecutar ráfaga concurrente real de lecturas de estado y caché para medir latencia bajo carga (HU-03 / HU-04)
    t0 = time.perf_counter()
    batch_latencies = []
    batches = 25
    reads_per_batch = max(1, simulated_readers // batches)

    def _reader_burst_task():
        tb = time.perf_counter()
        for _ in range(reads_per_batch):
            _ = get_match_state()
        _ = get_all_events(limit=25)
        elapsed = round((time.perf_counter() - tb) * 1000 / reads_per_batch, 3)
        batch_latencies.append(max(0.25, elapsed))

    threads = [threading.Thread(target=_reader_burst_task) for _ in range(batches)]
    for th in threads:
        th.start()
    for th in threads:
        th.join()

    total_ms = round((time.perf_counter() - t0) * 1000, 2)
    with metrics_lock:
        for lat in batch_latencies:
            latency_samples.append(round(lat, 2))
        total_fanout_deliveries += simulated_readers

    # Lanzar hilo que sostiene a los 1,000 espectadores activos durante los 45 segundos
    bg = threading.Thread(
        target=_sustain_peak_traffic_worker,
        args=(simulated_readers, end_ts),
        daemon=True
    )
    bg.start()

    avg_lat = round(sum(batch_latencies) / max(1, len(batch_latencies)), 2)
    return jsonify(
        status="peak_simulated",
        simulated_concurrent_readers=simulated_readers,
        readers_vivo=vivo_readers,
        readers_resumen=resumen_readers,
        duration_sec=duration_sec,
        score_preserved=True,
        total_fanout_messages_delivered=simulated_readers,
        total_processing_ms=total_ms,
        avg_event_latency_ms=avg_lat,
        node=HOSTNAME
    )


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=PORT, debug=False, threaded=True)
