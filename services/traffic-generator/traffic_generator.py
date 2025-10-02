import requests
import pandas as pd
import numpy as np
import os
import time
import random
import json
import redis

# --- CONFIGURACIÓN ---
BACKEND_URL = os.environ.get("BACKEND_URL", "http://llm:8000/answer")
DATA_PATH = os.environ.get("DATA_PATH", "/app/data/train.csv")
MAX_QUESTIONS = int(os.environ.get("MAX_QUESTIONS", 1000))
REQUEST_TIMEOUT_SECONDS = int(os.environ.get("REQUEST_TIMEOUT_SECONDS", 60))

CACHE_POLICY = os.environ.get("CACHE_POLICY", "LRU")
CACHE_SIZE = int(os.environ.get("CACHE_SIZE", 50))
LOG_FILE = os.environ.get("LOG_FILE", "/app/traffic_log.json")

REDIS_HOST = os.environ.get("REDIS_HOST", "redis")
REDIS_PORT = int(os.environ.get("REDIS_PORT", 6379))
REDIS_DB = int(os.environ.get("REDIS_DB", 0))

# --- CONEXIÓN A REDIS ---
r = redis.Redis(host=REDIS_HOST, port=REDIS_PORT, db=REDIS_DB, decode_responses=True)

# --- FUNCIONES DE CACHE ---
def get_from_cache(q_id):
    cached = r.hget("cache_data", str(q_id))
    if cached:
        cached_dict = json.loads(cached)
        if CACHE_POLICY == "LRU":
            r.lrem("cache_order", 0, str(q_id))
            r.rpush("cache_order", str(q_id))
        r.hincrby("cache_hits", "count", 1)
        return cached_dict
    else:
        r.hincrby("cache_misses", "count", 1)
        return None

def add_to_cache(q_id, response):
    q_id_str = str(q_id)
    if r.hexists("cache_data", q_id_str):
        if CACHE_POLICY == "LRU":
            r.lrem("cache_order", 0, q_id_str)
            r.rpush("cache_order", q_id_str)
        r.hset("cache_data", q_id_str, json.dumps(response))
    else:
        while r.llen("cache_order") >= CACHE_SIZE:
            evict_id = r.lpop("cache_order")
            if evict_id:
                r.hdel("cache_data", evict_id)
        r.hset("cache_data", q_id_str, json.dumps(response))
        r.rpush("cache_order", q_id_str)

def get_cache_stats():
    hits = int(r.hget("cache_hits", "count") or 0)
    misses = int(r.hget("cache_misses", "count") or 0)
    total = hits + misses
    hit_rate = (hits / total) * 100 if total > 0 else 0.0
    return hits, misses, hit_rate

# --- FUNCIONES AUXILIARES ---
def get_question_text(questions: pd.DataFrame, q_id: int) -> str:
    try:
        return questions.loc[q_id, 1]
    except KeyError:
        raise KeyError(f"Columna índice 1 no encontrada o ID {q_id} fuera de rango.")

# --- FUNCION PRINCIPAL ---
def run_traffic(mode: str, interval_rate: float, num_requests: int, questions_df: pd.DataFrame):
    random.seed(42)
    question_ids = questions_df.index.tolist()
    logs = []

    print(f"--- INICIANDO TRÁFICO ({mode.upper()}) ---")

    for i in range(num_requests):
        wait_time = np.random.exponential(scale=interval_rate) if mode == "poisson" else interval_rate
        time.sleep(max(0, wait_time))

        q_idx = random.choice(question_ids)
        try:
            pregunta_text = get_question_text(questions_df, q_idx)
            db_id = q_idx + 1
        except KeyError as e:
            print(f"[ERROR] {e}")
            continue

        cached = get_from_cache(db_id)
        if cached:
            source = "cache"
            score = cached.get('score', 0.0)
            result = cached
        else:
            try:
                payload = {"id": db_id, "pregunta": pregunta_text}
                response = requests.post(BACKEND_URL, json=payload, timeout=REQUEST_TIMEOUT_SECONDS)
                response.raise_for_status()
                result = response.json()

                # SCORE SIMULADO
                result['score'] = round(random.uniform(0, 1), 4)
                score = result['score']
                source = result.get('source', 'llm')

                add_to_cache(db_id, result)
            except requests.exceptions.RequestException as e:
                source = 'N/A'
                score = None
                print(f"Req {i+1} [ID:{db_id}] -> ERROR: {e}")
                continue

        log_entry = {
            "req_num": i + 1,
            "id": db_id,
            "source": source,
            "score": score,
            "timestamp": time.time()
        }
        logs.append(log_entry)

        print(f"Req {i+1} [ID:{db_id}] -> Fuente: {source} | Score: {score}")

    with open(LOG_FILE, "w") as f:
        json.dump(logs, f, indent=2)

    hits, misses, hit_rate = get_cache_stats()
    print("\n--- RESUMEN CACHE ---")
    print(f"Política: {CACHE_POLICY}, Tamaño máximo: {CACHE_SIZE}")
    print(f"Hits: {hits}, Misses: {misses}, Hit Rate: {hit_rate:.2f}%")

# --- MAIN ---
if __name__ == "__main__":
    print("Esperando 5 segundos para asegurar que los servicios estén listos...")
    time.sleep(5)

    try:
        questions_df = pd.read_csv(DATA_PATH, header=None).head(MAX_QUESTIONS).reset_index(drop=True)
        run_traffic(mode="uniform", interval_rate=2.0, num_requests=50, questions_df=questions_df)
    except FileNotFoundError:
        print(f"[ERROR] No se encontró el archivo de datos: {DATA_PATH}")
    except Exception as e:
        print(f"[ERROR] Fallo general en traffic generator: {e}")

