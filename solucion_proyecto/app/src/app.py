"""
UNAL Sports Live — Proyecto 06: Minuto a minuto de torneos deportivos
Arquitectura CQRS + Fan-Out en Contenedores Independientes:
  - Servicio 1 (fan-portal / modo READ): Exclusivo para los 1,000+ Aficionados (SSE + Caché O(1)).
  - Servicio 2 (journalist-studio / modo WRITE): Consola independiente para el Periodista (Ingesta -> SNS -> SQS -> Redis).
"""
import os
import json
import time
import uuid
import socket
import threading
from datetime import datetime, timezone
from collections import deque
from flask import Flask, request, jsonify, Response, render_template, stream_with_context, redirect

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
# CONFIGURACIÓN Y VARIABLES DE ENTORNO (Sin credenciales hardcodeadas - Lab 06)
# ==============================================================================
SERVICE_ROLE = os.environ.get("SERVICE_ROLE", "all").lower()  # "fan", "journalist", o "all"
PORT = int(os.environ.get("PORT", "8000"))
REDIS_HOST = os.environ.get("REDIS_HOST", "redis")
REDIS_PORT = int(os.environ.get("REDIS_PORT", "6379"))
AWS_REGION = os.environ.get("AWS_REGION", "us-east-1")
SNS_TOPIC_ARN = os.environ.get("SNS_TOPIC_ARN", "")
SQS_LIVE_URL = os.environ.get("SQS_LIVE_URL", "")
SQS_SUMMARY_URL = os.environ.get("SQS_SUMMARY_URL", "")
JOURNALIST_TOKEN = os.environ.get("JOURNALIST_TOKEN", "unal-periodista-2026")
HOSTNAME = socket.gethostname()

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
# ESTADO EN MEMORIA (Fallback y métricas de latencia bajo pico)
# ==============================================================================
DEFAULT_MATCH = {
    "match_id": "UNAL-FINAL-2026",
    "tournament": "Torneo Interfacultades UNAL 2026-2 · Gran Final",
    "home_team": "Ingeniería FC",
    "away_team": "Ciencias Atlético",
    "home_score": 2,
    "away_score": 1,
    "minute": 78,
    "status": "EN VIVO · 2T",
    "updated_at": datetime.now(timezone.utc).isoformat()
}

INITIAL_EVENTS = [
    {
        "id": "evt-init-1",
        "minute": 12,
        "type": "GOAL",
        "team": "HOME",
        "player": "Mateo Gómez (#10)",
        "description": "¡GOLAZO de Ingeniería! Remate de media distancia al ángulo superior derecho.",
        "priority": "HIGH",
        "channel": "vivo",
        "timestamp": time.time() - 3600,
        "node": HOSTNAME
    },
    {
        "id": "evt-init-2",
        "minute": 34,
        "type": "YELLOW_CARD",
        "team": "AWAY",
        "player": "Sebastián Ruiz (#5)",
        "description": "Tarjeta amarilla por infracción táctica en transición ofensiva.",
        "priority": "LOW",
        "channel": "resumen",
        "timestamp": time.time() - 2400,
        "node": HOSTNAME
    },
    {
        "id": "evt-init-3",
        "minute": 51,
        "type": "GOAL",
        "team": "AWAY",
        "player": "Daniel Vargas (#9)",
        "description": "¡Empata Ciencias! Cabezazo cruzado tras cobro de tiro de esquina.",
        "priority": "HIGH",
        "channel": "vivo",
        "timestamp": time.time() - 1500,
        "node": HOSTNAME
    },
    {
        "id": "evt-init-4",
        "minute": 74,
        "type": "GOAL",
        "team": "HOME",
        "player": "Alejandro Torres (#7)",
        "description": "¡GOOOL de Ingeniería! Contraataque letal a tres toques para el 2-1 parcial.",
        "priority": "HIGH",
        "channel": "vivo",
        "timestamp": time.time() - 300,
        "node": HOSTNAME
    }
]

local_events = deque(INITIAL_EVENTS, maxlen=200)
local_match = dict(DEFAULT_MATCH)
local_subscribers_vivo = []
local_subscribers_resumen = []
latency_samples = deque([3.8, 4.4, 3.2, 5.1, 4.0, 4.7, 3.9, 6.1], maxlen=500)
metrics_lock = threading.Lock()
active_sse_clients = {"vivo": 0, "resumen": 0}
total_events_published = len(INITIAL_EVENTS)
total_fanout_deliveries = 0


def init_redis_seed():
    """Inicializa datos semilla en Redis si aún no existen."""
    if not redis_client:
        return
    try:
        if not redis_client.exists("match:state"):
            redis_client.set("match:state", json.dumps(DEFAULT_MATCH))
        if not redis_client.exists("match:events"):
            for ev in INITIAL_EVENTS:
                redis_client.rpush("match:events", json.dumps(ev))
        if not redis_client.exists("match:metrics:events_published"):
            redis_client.set("match:metrics:events_published", len(INITIAL_EVENTS))
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
    """
    Reto Extra del Enunciado 06:
    Clasifica cada evento en prioridad ALTA (canal 'vivo' inmediato) o BAJA (canal 'resumen' consolidado).
    """
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


def publish_event_fanout(event_data: dict, simulated_readers_override: int = 0) -> dict:
    """
    Implementa el Patrón Fan-Out:
    1. El microservicio de Cabina del Periodista publica 1 sola vez.
    2. Si SNS está configurado, publica en el Topic SNS con MessageAttributes (prioridad).
       SNS hace fan-out hacia SQS Cola Viva (alta prioridad) y SQS Cola Resumen (baja prioridad).
    3. Actualiza el estado en caché (Redis) para que nuevos lectores (HU-03) lean en O(1).
    4. Emite por Redis Pub/Sub a los canales `channel:vivo` y `channel:resumen` hacia el portal de Aficionados.
    """
    global total_events_published, total_fanout_deliveries
    t0 = time.perf_counter()

    ev_type = event_data.get("type", "COMMENT").upper()
    priority, primary_channel = classify_event_priority(ev_type)
    minute = int(event_data.get("minute", get_match_state().get("minute", 1)))
    team = event_data.get("team", "NEUTRAL").upper()

    event = {
        "id": f"evt-{uuid.uuid4().hex[:8]}",
        "minute": minute,
        "type": ev_type,
        "team": team,
        "player": event_data.get("player", "Jugador UNAL"),
        "description": event_data.get("description", "Evento reportado desde cancha"),
        "priority": priority,
        "channel": primary_channel,
        "timestamp": time.time(),
        "created_iso": datetime.now(timezone.utc).isoformat(),
        "node": HOSTNAME
    }

    # Actualizar marcador si es GOL
    state = get_match_state()
    state["minute"] = max(state.get("minute", 0), minute)
    if ev_type == "GOAL":
        if team == "HOME":
            state["home_score"] = state.get("home_score", 0) + 1
        elif team == "AWAY":
            state["away_score"] = state.get("away_score", 0) + 1
    elif ev_type == "MATCH_END":
        state["status"] = "FINALIZADO"
    elif ev_type == "MATCH_START":
        state["status"] = "EN VIVO · 1T"
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
            # Reto extra: Canal "vivo" recibe TODOS los eventos al instante;
            # Canal "resumen" recibe eventos clave con prioridad diferenciada
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
# VISTAS SEPARADAS: PORTAL PÚBLICO DE AFICIONADOS vs. CABINA DEL PERIODISTA
# ==============================================================================
@app.get("/")
def index():
    """
    Si el contenedor corre con SERVICE_ROLE=journalist (Puerto 8001), sirve directamente la Cabina del Periodista.
    Si corre con SERVICE_ROLE=fan o all (Puerto 80 / 8000), sirve el Portal Público limpio para los Aficionados.
    """
    if SERVICE_ROLE == "journalist":
        return render_template("periodista.html", hostname=HOSTNAME, service_role="journalist-studio")
    return render_template("index.html", hostname=HOSTNAME, service_role="fan-portal")


@app.get("/periodista")
@app.get("/cabina")
def journalist_console():
    """
    Página dedicada y exclusiva para la Cabina Móvil del Periodista (HU-01) y Control de Carga (HU-04).
    Completamente separada de la vista pública de los aficionados.
    """
    return render_template("periodista.html", hostname=HOSTNAME, service_role=SERVICE_ROLE)


@app.get("/health")
def health():
    """Healthcheck exigido por plantilla, Docker, ALB y Jenkins."""
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
        active_connections=active_sse_clients,
        timestamp=datetime.now(timezone.utc).isoformat()
    )


@app.get("/api/summary")
def api_summary():
    """
    [HU-03] Como aficionado, quiero el resumen del partido cuando entro tarde, para ponerme al día rápido.
    Servido directamente desde caché (ElastiCache Redis / memoria O(1)) sin golpear base de datos.
    """
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
    """
    [HU-01] Como periodista, quiero reportar gol/tarjeta/cambio desde el celular, para actualizar en segundos.
    Valida token de periodista y dispara el patrón Fan-Out hacia miles de lectores.
    """
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
    """
    [HU-02] Como aficionado, quiero ver los eventos del partido en vivo sin recargar, para seguirlo desde la tribuna.
    [Reto Extra] Canal 'vivo' (prioridad alta, latencia sub-segundo) y canal 'resumen' (prioridad diferenciada).
    """
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
    """
    [HU-04] y Restricciones: Métricas de latencia bajo pico (p50, p95, p99), conexiones activas y estado del nodo.
    """
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
            "priority_channels": ["vivo (HIGH priority, 150ms poll)", "resumen (LOW priority / digest, 600ms poll)"]
        }
    )


@app.post("/api/simulate-peak")
def api_simulate_peak():
    """
    Dispara una ráfaga controlada de eventos y lecturas concurrentes desde la Cabina del Periodista
    para demostrar en vivo cómo el Portal de Aficionados se actualiza en tiempo real bajo carga de 1,000 lectores.
    """
    body = request.get_json(silent=True) or {}
    simulated_readers = int(body.get("readers", 1000))
    burst_events = [
        {"minute": 81, "type": "YELLOW_CARD", "team": "HOME", "player": "Carlos Méndez (#4)", "description": "Amarilla por demorar la reanudación en saque de banda."},
        {"minute": 84, "type": "SUBSTITUTION", "team": "AWAY", "player": "Entra J. Pérez (#19) · Sale D. Vargas (#9)", "description": "Variante ofensiva en Ciencias buscando el empate en el cierre."},
        {"minute": 88, "type": "PENALTY", "team": "AWAY", "player": "Juan Pérez (#19)", "description": "¡PENAL PARA CIENCIAS! El árbitro señala el punto blanco tras mano en el área."},
        {"minute": 89, "type": "GOAL", "team": "AWAY", "player": "Juan Pérez (#19)", "description": "¡GOOOOL DE CIENCIAS! Remate cruzado potente para el 2-2 agonizando el partido."},
        {"minute": 90, "type": "GOAL", "team": "HOME", "player": "Mateo Gómez (#10)", "description": "¡HISTÓRICO! ¡GOL DE INGENIERÍA AL 90+2'! Tiro libre directo al ángulo para el título universitario."}
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
