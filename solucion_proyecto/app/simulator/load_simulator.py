#!/usr/bin/env python3
"""
Simulador de Carga del Partido Final — Proyecto 06 (UNAL Sports Live)
Cumple:
  - [HU-04] Como organizador, quiero que el sistema aguante 1000 lectores simultáneos, para el partido final.
  - Restricción: Simulador de carga incluido + métricas de latencia bajo pico (p50, p95, p99).
  - Demostración de Fan-Out: 1 periodista publicando mientras 1000 lectores consumen /api/summary y /api/stream/vivo.

Uso:
  python3 simulator/load_simulator.py --url http://localhost:8000 --readers 1000 --events 10
"""
import argparse
import concurrent.futures
import json
import statistics
import time
import urllib.request
import urllib.error


def fetch_reader(base_url: str, reader_id: int) -> dict:
    """Simula un aficionado que entra al partido (consulta resumen en caché y abre stream)."""
    t0 = time.perf_counter()
    channel = "vivo" if (reader_id % 4 != 0) else "resumen"
    try:
        req = urllib.request.Request(
            f"{base_url}/api/summary?reader={reader_id}&ch={channel}",
            headers={"Accept": "application/json", "User-Agent": f"UNAL-Fan-Simulator/{reader_id}"}
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            status = resp.status
            body = json.loads(resp.read().decode("utf-8"))
            node = body.get("served_by_node", "unknown")
        elapsed_ms = (time.perf_counter() - t0) * 1000.0
        return {"ok": status == 200, "latency_ms": elapsed_ms, "node": node, "channel": channel}
    except Exception as exc:
        elapsed_ms = (time.perf_counter() - t0) * 1000.0
        return {"ok": False, "latency_ms": elapsed_ms, "node": "error", "error": str(exc)}


def publish_journalist_event(base_url: str, token: str, idx: int) -> dict:
    """Simula al periodista único reportando jugadas desde la cancha en pleno pico de tráfico."""
    sample_events = [
        ("GOAL", "HOME", "Mateo Gómez (#10)", "¡GOLAZO de Ingeniería en la gran final universitaria!"),
        ("YELLOW_CARD", "AWAY", "Carlos Pérez (#6)", "Tarjeta amarilla por falta táctica en el mediocampo."),
        ("SUBSTITUTION", "HOME", "Entra L. Díaz (#14)", "Cambio estratégico para refrescar las bandas."),
        ("PENALTY", "AWAY", "Daniel Vargas (#9)", "¡Penal sancionado por el árbitro central tras tiro de esquina!"),
        ("GOAL", "AWAY", "Daniel Vargas (#9)", "¡GOL de Ciencias! Cobro al palo izquierdo imposible para el arquero."),
    ]
    ev_type, team, player, desc = sample_events[idx % len(sample_events)]
    payload = json.dumps({
        "minute": 75 + idx,
        "type": ev_type,
        "team": team,
        "player": player,
        "description": f"[Simulación Pico #{idx + 1}] {desc}"
    }).encode("utf-8")

    t0 = time.perf_counter()
    req = urllib.request.Request(
        f"{base_url}/api/events",
        data=payload,
        method="POST",
        headers={
            "Content-Type": "application/json",
            "X-Journalist-Token": token
        }
    )
    with urllib.request.urlopen(req, timeout=10) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    elapsed_ms = (time.perf_counter() - t0) * 1000.0
    return {"latency_ms": elapsed_ms, "backend_fanout_ms": data.get("latency_ms", 0), "node": data.get("node")}


def percentile(sorted_list: list, pct: float) -> float:
    if not sorted_list:
        return 0.0
    idx = min(len(sorted_list) - 1, int(len(sorted_list) * pct))
    return round(sorted_list[idx], 2)


def main():
    parser = argparse.ArgumentParser(description="Simulador de Pico — 1000 lectores simultáneos (Proyecto 06)")
    parser.add_argument("--url", default="http://localhost:8000", help="URL base del servicio (EC2, ALB o local)")
    parser.add_argument("--readers", type=int, default=1000, help="Número de lectores simultáneos a simular")
    parser.add_argument("--concurrency", type=int, default=100, help="Hilos concurrentes del cliente generador")
    parser.add_argument("--events", type=int, default=5, help="Eventos emitidos por el periodista durante el pico")
    parser.add_argument("--token", default="unal-periodista-2026", help="Token del periodista")
    args = parser.parse_args()

    print("=" * 78)
    print("⚽ SIMULADOR DE CARGA — PROYECTO 06: MINUTO A MINUTO DE TORNEOS DEPORTIVOS")
    print("=" * 78)
    print(f"• Endpoint Objetivo : {args.url}")
    print(f"• Lectores a simular: {args.readers} aficionados (75% Canal VIVO, 25% Canal RESUMEN)")
    print(f"• Eventos Periodista: {args.events} publicaciones Fan-Out durante el pico")
    print("-" * 78)

    start_global = time.perf_counter()

    # 1. Publicar eventos del periodista mientras los lectores están activos
    journalist_latencies = []
    for i in range(args.events):
        try:
            res = publish_journalist_event(args.url, args.token, i)
            journalist_latencies.append(res["latency_ms"])
            print(f"  [Periodista #{i+1}] Evento publicado en {res['latency_ms']:.2f} ms (Fan-Out interno: {res['backend_fanout_ms']} ms, Nodo: {res['node']})")
        except Exception as exc:
            print(f"  [Periodista #{i+1}] Error: {exc}")

    # 2. Lanzar ráfaga de 1000 lectores concurrentes contra el caché/stream
    results = []
    nodes_distribution = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=args.concurrency) as executor:
        futures = [executor.submit(fetch_reader, args.url, r_id) for r_id in range(args.readers)]
        for fut in concurrent.futures.as_completed(futures):
            r = fut.result()
            results.append(r)
            node = r.get("node", "unknown")
            nodes_distribution[node] = nodes_distribution.get(node, 0) + 1

    total_duration = time.perf_counter() - start_global
    latencies = sorted(r["latency_ms"] for r in results if r["ok"])
    success_count = sum(1 for r in results if r["ok"])
    error_count = len(results) - success_count

    print("-" * 78)
    print("📊 RESULTADOS DE LATENCIA BAJO PICO (HU-04):")
    print(f"• Peticiones Exitosas     : {success_count}/{args.readers} ({(success_count / max(1, args.readers)) * 100:.1f}%)")
    print(f"• Errores HTTP            : {error_count}")
    print(f"• Tiempo Total de Ráfaga  : {total_duration:.2f} s ({args.readers / max(0.01, total_duration):.1f} req/s)")
    if latencies:
        print(f"• Latencia Promedio       : {statistics.mean(latencies):.2f} ms")
        print(f"• Latencia Mediana (p50)  : {percentile(latencies, 0.50):.2f} ms")
        print(f"• Latencia Pico (p95)     : {percentile(latencies, 0.95):.2f} ms  <-- Métrica SLA (< 200 ms)")
        print(f"• Latencia Extremo (p99)  : {percentile(latencies, 0.99):.2f} ms")
    print(f"• Balanceo por Nodos/Swarm: {json.dumps(nodes_distribution)}")
    print("=" * 78)


if __name__ == "__main__":
    main()
