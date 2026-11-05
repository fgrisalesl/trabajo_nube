"""
SQS Fan-Out Consumer Worker (AWS SNS -> SQS Live & Summary Queues -> Redis ElastiCache Pub/Sub)
En el despliegue AWS, SNS publica en dos colas SQS con distinta prioridad:
  1. SQS_LIVE_URL: Cola de prioridad ALTA (Long Polling inmediato, entrega sub-segundo al canal 'vivo').
  2. SQS_SUMMARY_URL: Cola de prioridad BAJA / Resumen (Batching de eventos para actualizar estadísticas y canal 'resumen').
Si las colas SQS no están configuradas (modo local Docker Compose), este worker permanece en espera pasiva.
"""
import os
import json
import time
import threading

try:
    import boto3
    import redis
except ImportError:
    boto3 = None
    redis = None

AWS_REGION = os.environ.get("AWS_REGION", "us-east-1")
SQS_LIVE_URL = os.environ.get("SQS_LIVE_URL", "")
SQS_SUMMARY_URL = os.environ.get("SQS_SUMMARY_URL", "")
REDIS_HOST = os.environ.get("REDIS_HOST", "redis")
REDIS_PORT = int(os.environ.get("REDIS_PORT", "6379"))


def poll_queue(queue_url: str, channel_name: str, poll_wait: int, sleep_between: float):
    sqs = boto3.client("sqs", region_name=AWS_REGION)
    rc = redis.Redis(host=REDIS_HOST, port=REDIS_PORT, decode_responses=True)
    print(f"[Worker-{channel_name}] Escuchando cola SQS: {queue_url}")

    while True:
        try:
            resp = sqs.receive_message(
                QueueUrl=queue_url,
                MaxNumberOfMessages=10,
                WaitTimeSeconds=poll_wait,
                MessageAttributeNames=["All"]
            )
            messages = resp.get("Messages", [])
            for msg in messages:
                body = json.loads(msg["Body"])
                # Si viene envuelto por SNS Envelope, extraer Message
                payload = body.get("Message", msg["Body"])
                rc.publish(f"channel:{channel_name}", payload)
                sqs.delete_message(QueueUrl=queue_url, ReceiptHandle=msg["ReceiptHandle"])
            if sleep_between > 0:
                time.sleep(sleep_between)
        except Exception as exc:
            print(f"[Worker-{channel_name}] Error procesando SQS: {exc}")
            time.sleep(5)


def main():
    if not (boto3 and redis and (SQS_LIVE_URL or SQS_SUMMARY_URL)):
        print("[SQS-Worker] Modo local detectado (sin colas AWS SQS configuradas). Fan-out directo vía Redis Pub/Sub activo.")
        while True:
            time.sleep(60)

    threads = []
    if SQS_LIVE_URL:
        t1 = threading.Thread(target=poll_queue, args=(SQS_LIVE_URL, "vivo", 20, 0.0), daemon=True)
        t1.start()
        threads.append(t1)
    if SQS_SUMMARY_URL:
        t2 = threading.Thread(target=poll_queue, args=(SQS_SUMMARY_URL, "resumen", 10, 2.0), daemon=True)
        t2.start()
        threads.append(t2)

    for t in threads:
        t.join()


if __name__ == "__main__":
    main()
