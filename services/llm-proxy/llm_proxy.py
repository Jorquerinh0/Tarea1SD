import redis
import json
import random
import time
import requests
import os
from fastapi import FastAPI, BackgroundTasks
from pydantic import BaseModel

# --- CONFIGURACIÓN DE SERVICIOS ---
SCORER_SERVICE_URL = os.environ.get("SCORER_SERVICE_URL", "http://scorer:8000")
UPDATE_COUNT_URL = f"{SCORER_SERVICE_URL}/update_count"
SCORE_SAVE_URL = f"{SCORER_SERVICE_URL}/score_and_save"

REDIS_HOST = os.environ.get("REDIS_HOST", "redis")
REDIS_PORT = int(os.environ.get("REDIS_PORT", 6379))
CACHE_CAPACITY = 50 

random.seed(42)
app = FastAPI()

# --- MODELOS DE DATOS ---
class QuestionRequest(BaseModel):
    id: int
    pregunta: str

class Response(BaseModel): # Modelo unificado para la respuesta del endpoint
    id: int
    pregunta: str
    respuesta_llm: str
    score: float = 0.0
    source: str

# --- CONEXIÓN A REDIS ---
try:
    r = redis.Redis(host=REDIS_HOST, port=REDIS_PORT, decode_responses=True)
    r.config_set('maxmemory', f'100mb') 
    r.config_set('maxmemory-policy', 'allkeys-lru')
    r.ping()
    print("Conexión a Redis exitosa.")
except Exception as e:
    print(f"Error de conexión a Redis: {e}")
    r = None

# --- FUNCIONES DE CACHÉ (LRU Personalizada del usuario) ---
def get_from_cache(key: str):
    """Obtiene un valor desde la caché y actualiza la posición LRU."""
    if not r: return None
    
    cached_data = r.hget("cache_data", key) 
    if cached_data:
        r.lrem("lru_list", 0, key)
        r.rpush("lru_list", key)
        return json.loads(cached_data)
    return None

def set_to_cache(key: str, value: dict):
    """Guarda un valor en la caché aplicando política LRU."""
    if not r: return
    
    r.hset("cache_data", key, json.dumps(value))
    
    r.lrem("lru_list", 0, key)
    r.rpush("lru_list", key)

    if r.llen("lru_list") > CACHE_CAPACITY:
        oldest_key = r.lpop("lru_list")
        if oldest_key:
            r.hdel("cache_data", oldest_key)
            print(f"LRU Eviction: Key {oldest_key} eliminada de la caché.")

# --- TAREAS EN SEGUNDO PLANO (Bloqueantes) ---
def update_score_count_async(data: QuestionRequest):
    """CACHE HIT: Llama al Scorer para solo aumentar el contador (ejecutado en BackgroundTask)."""
    try:
        count_data = {"id": data.id} 
        
        response = requests.post(UPDATE_COUNT_URL, json=count_data, timeout=2)
        response.raise_for_status()
        print(f"Contador de hit de caché actualizado para ID {data.id}")
    except requests.exceptions.RequestException as e:
        print(f"Advertencia: Fallo al actualizar el contador de caché (ID {data.id}): {e}")
    except Exception as e:
        print(f"Advertencia: Error inesperado al actualizar conteo (ID {data.id}): {e}")

def call_llm_and_score_async(data: QuestionRequest, respuesta_llm: str):
    """
    LLM MISS:
    1. Llama al Scorer para calcular score y guardar en la DB.
    2. Guarda la respuesta LLM + Score en Redis.
    (Ejecutado en BackgroundTask)
    """
    req_id = data.id
    key = str(req_id)
    
    score_data = {
        "id": req_id,
        "pregunta": data.pregunta,
        "respuesta_llm": respuesta_llm
    }
    
    try:
        # 1. Llamar a Scorer
        response = requests.post(SCORE_SAVE_URL, json=score_data, timeout=5)
        response.raise_for_status()
        
        score = response.json().get('score', 0.0)
        print(f"Scorer completado para ID {req_id}. Score: {score}")

        # 2. Guardar en caché (utiliza la función LRU personalizada)
        cache_value = {
            "respuesta_llm": respuesta_llm,
            "score": score
        }
        set_to_cache(key, cache_value) 
        print(f"Cache Miss: Respuesta y Score guardados en Redis para ID {req_id}.")
        
    except requests.exceptions.RequestException as e:
        print(f"ERROR: Fallo de red o Scorer durante cache miss (ID {req_id}): {e}")
    except Exception as e:
        print(f"ERROR inesperado durante el scoring/cacheo (ID {req_id}): {e}")

# --- SIMULACIÓN DE LLM ---
def simulate_llm_response(pregunta: str) -> str:
    """Simula latencia y respuesta de un LLM real."""
    time.sleep(1.0) # 1.0s de demora
    random.seed(hash(pregunta) % 10000) 
    return f"Respuesta LLM (ID {random.randint(1000, 9999)}): 'La respuesta a su pregunta sobre {pregunta[:20]}... es un hecho conocido.'"

# --- LÓGICA DE VARIACIÓN DE SCORE ---
def apply_score_fluctuation(base_score: float) -> float:
    """Aplica una variación aleatoria simulada al score base."""
    # Simula la misma variación de +/- 0.05 que el Scorer
    fluctuation = random.uniform(-0.05, 0.05)
    new_score = base_score + fluctuation
    # Asegura que el score final esté en el rango [0.0, 1.0]
    return max(0.0, min(1.0, new_score))


# --- ENDPOINT PRINCIPAL ---
@app.post("/answer", response_model=Response)
async def get_llm_answer(data: QuestionRequest, background_tasks: BackgroundTasks):
    key = str(data.id)

    # 1. Intentar caché
    cached_result = get_from_cache(key)
    if cached_result:
        # Tarea en segundo plano para actualizar el contador
        background_tasks.add_task(update_score_count_async, data)
        
        # --- LÓGICA DE VARIACIÓN DE SCORE EN CACHE HIT (FIX) ---
        base_score = cached_result.get("score", 0.0)
        simulated_score = apply_score_fluctuation(base_score)
        
        print(f"CACHE HIT: ID {data.id} atendida desde Redis. Score Base: {base_score:.4f}, Score Fluctuante: {simulated_score:.4f}")
        
        return Response(
            id=data.id,
            pregunta=data.pregunta,
            respuesta_llm=cached_result.get("respuesta_llm", ""),
            score=simulated_score, # Devolver el score variable
            source="cache"
        )

    # 2. Cache miss: generar respuesta (LLM Lento)
    print(f"CACHE MISS: ID {data.id} llamando al LLM simulado...")
    respuesta_llm = simulate_llm_response(data.pregunta)

    # 3. Almacenamiento Asíncrono (Scoring & Caching)
    # El score retornado aquí será 0.0, el score real se calculará en background.
    background_tasks.add_task(call_llm_and_score_async, data, respuesta_llm)

    # 4. Devolver respuesta INMEDIATA (con score 0.0, el cliente usará la respuesta cacheada después)
    return Response(
        id=data.id,
        pregunta=data.pregunta,
        respuesta_llm=respuesta_llm,
        score=0.0, 
        source="llm"
    )

@app.get("/health")
def health():
    return {"status": "ok", "cache_enabled": bool(r)}

