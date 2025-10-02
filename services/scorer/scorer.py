from fastapi import FastAPI, HTTPException
import psycopg2
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity
import numpy as np
import os
import requests
import json
from pydantic import BaseModel

# --- MODELO DE DATOS RECIBIDO ---
class ScoreRequest(BaseModel):
    id: int # ID del registro en la BD
    pregunta: str
    respuesta_llm: str

app = FastAPI()

# --- CONEXIÓN A POSTGRES ---
def get_db_connection():
    try:
        return psycopg2.connect(os.environ['DATABASE_URL'])
    except Exception as e:
        print(f"Error de conexión a DB: {e}")
        return None

# --- MÉTRICA DE CALIDAD: Similitud de Coseno (TF-IDF) ---
def calculate_score(text1: str, text2: str) -> float:
    """Calcula la similitud de coseno entre dos textos usando TF-IDF."""
    
    # Normalización
    text1 = text1.lower()
    text2 = text2.lower()

    documents = [text1, text2]
    
    # Si ambos textos están vacíos o son muy cortos, devolvemos 0.0
    if not text1 or not text2:
        return 0.0

    # Usar 'spanish' stop words y ngrams(1, 2) para mejor contexto
    vectorizer = TfidfVectorizer(stop_words='spanish', ngram_range=(1, 2))
    
    # Manejar caso de matriz degenerada (solo palabras vacías)
    try:
        tfidf_matrix = vectorizer.fit_transform(documents)
    except ValueError:
        return 0.0 # Error si la matriz está vacía
    
    # Calcular la similitud de coseno entre los dos vectores
    similarity_score = cosine_similarity(tfidf_matrix[0:1], tfidf_matrix[1:2])[0][0]
    return float(similarity_score)

# --- ENDPOINTS ---

@app.post("/update_count")
async def update_repetition_count(item: ScoreRequest): # Uso correcto del modelo ScoreRequest
    """Actualiza el contador de repeticiones (llamado por el LLM-Proxy en caso de HIT)."""
    conn = get_db_connection()
    if not conn:
        raise HTTPException(status_code=500, detail="Database connection error")
    
    try:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE respuestas_analisis SET conteo_repeticiones = conteo_repeticiones + 1 WHERE id = %s;",
                (item.id,)
            )
        conn.commit()
        return {"status": "success", "message": f"Count updated for ID: {item.id}"}
    except Exception as e:
        conn.rollback()
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        if conn:
            conn.close()


@app.post("/score_and_save")
async def score_and_save(data: ScoreRequest):
    """Calcula el score, actualiza el registro en la BD y lo devuelve (llamado por el LLM-Proxy en caso de MISS)."""
    conn = get_db_connection()
    if not conn:
        raise HTTPException(status_code=500, detail="Database connection error")

    try:
        # 1. Obtener respuesta original del dataset
        with conn.cursor() as cur:
            # **CORRECCIÓN CLAVE:** Usar la columna 'mejor_respuesta'
            cur.execute(
                "SELECT mejor_respuesta FROM respuestas_analisis WHERE id = %s;",
                (data.id,)
            )
            result = cur.fetchone()
        
        if not result:
            print(f"Error: Question ID {data.id} not found in database for scoring.")
            raise HTTPException(status_code=404, detail="Question ID not found in database")
        
        respuesta_original = result[0]
        
        # 2. Calcular el Score
        score = calculate_score(data.respuesta_llm, respuesta_original)
        
        # 3. Guardar respuesta LLM, score y actualizar conteo (el primer conteo es 1)
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE respuestas_analisis 
                SET respuesta_llm = %s, puntaje_calidad = %s, conteo_repeticiones = conteo_repeticiones + 1
                WHERE id = %s;
                """,
                (data.respuesta_llm, score, data.id)
            )
        conn.commit()
        
        print(f"ID {data.id}: Score calculado ({score:.4f}) y guardado.")

        return {
            "id": data.id,
            "score": score,
            "respuesta_llm": data.respuesta_llm,
            "message": "Score calculated and data saved."
        }

    except Exception as e:
        conn.rollback()
        print(f"Scoring/Saving Error for ID {data.id}: {e}")
        raise HTTPException(status_code=500, detail=f"Scoring/Saving Error: {e}")
    finally:
        if conn:
            conn.close()

if __name__ == "__main__":
    import uvicorn
    # Usa el puerto 8001 para que no choque con el LLM-Proxy (8000)
    uvicorn.run(app, host="0.0.0.0", port=8001)

