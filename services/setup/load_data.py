import pandas as pd
import psycopg2
import time
import os
import sys

# --- CONEXIÓN A POSTGRES ---
def get_db_connection():
    """Intenta conectar con PostgreSQL con reintentos."""
    for i in range(15): # Intentar por 15 veces (hasta 75 segundos)
        try:
            conn = psycopg2.connect(
                host="postgres",  # Nombre del servicio en docker-compose
                database="yahoo_eval",
                user="postgres",
                password="postgres"
            )
            print("Conexión a PostgreSQL exitosa.")
            return conn
        except psycopg2.OperationalError as e:
            print(f"PostgreSQL no está listo. Reintentando en 5s... Intento {i+1}/15")
            time.sleep(5)
    raise Exception("No se pudo conectar a PostgreSQL después de varios intentos.")


# --- ESTRUCTURA DE LA TABLA ---
def create_table(conn):
    print("Creando tabla 'respuestas_analisis'...")
    with conn.cursor() as cur:
        cur.execute("DROP TABLE IF EXISTS respuestas_analisis CASCADE;") 
        
        # La respuesta LLM y el score se actualizan después
        cur.execute("""
            CREATE TABLE respuestas_analisis (
                id SERIAL PRIMARY KEY,
                pregunta_original TEXT NOT NULL,
                -- Columna para la respuesta original del dataset
                mejor_respuesta TEXT NOT NULL,
                respuesta_llm TEXT,
                puntaje_calidad REAL,
                conteo_repeticiones INTEGER NOT NULL DEFAULT 0
            );
        """)
    conn.commit()
    print("Tabla creada.")

# --- CARGA DE DATOS ---
def load_data(conn, file_path):
    print(f"Cargando datos desde {file_path}...")
    try:
        # Lee el CSV usando encoding latin1 para evitar errores
        df = pd.read_csv(file_path, encoding='latin1')
        df = df.head(10000) 
        
        # Actualizamos la consulta para usar 'mejor_respuesta'
        insert_query = """
            INSERT INTO respuestas_analisis (pregunta_original, mejor_respuesta)
            VALUES (%s, %s);
        """
        
        with conn.cursor() as cur:
            for index, row in df.iterrows():
                # Adaptación a nombres de columna comunes
                question = row.get('question_title') or row.get('question')
                answer = row.get('best_answer') or row.get('answer')
                
                if question and answer:
                    cur.execute(insert_query, (question, answer))
            
            conn.commit()
        print(f"Carga inicial de {len(df)} registros completada exitosamente.")
    
    except Exception as e:
        print(f"Error durante la carga de datos: {e}")
        conn.rollback()
        sys.exit(1)


if __name__ == "__main__":
    DATA_PATH = os.environ.get('DATA_PATH', '/app/data/train.csv')
    try:
        conn = get_db_connection()
        create_table(conn)
        load_data(conn, DATA_PATH)
        conn.close()
    except Exception as e:
        print(f"FALLO CRÍTICO en el setup: {e}")
        sys.exit(1)

