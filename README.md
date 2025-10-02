# Yahoo LLM Eval

Este proyecto implementa un entorno de simulación para evaluar el desempeño de un sistema de **LLM + caché** usando datos de Yahoo! Answers.  
La arquitectura está basada en **Docker Compose** y servicios modulares.

---

## 📂 Estructura del proyecto

```
yahoo-llm-eval/
│── data/
│    └── train.csv          # Dataset base con preguntas/respuestas
│
│── service/
│    ├── setup/             # Scripts iniciales y configuración
│	├── Dockerfile
│       └── *load_data.py
│    ├── llm_proxy/         # Servicio que conecta con el LLM (Gemini)
│	├── Dockerfile
│       └── *llm_proxy.py
│    ├── traffic_generator/ # Generador de tráfico (simulación de requests)
│	├── Dockerfile
│       └── *traffic_generator.py
│    └── score/             # Servicio de evaluación de respuestas
│       ├── Dockerfile
│       └── *score.py
│
│── docker-compose.yml      # Orquestación de servicios
│── requirements.txt        # Dependencias de Python
│── .env                    # Variables de entorno (llave de Gemini)
```

---

## ⚙️ Requisitos previos

- **Python 3.10+** y `venv` habilitado
- **Docker** y **Docker Compose**
- Llave de acceso a **Gemini API** (configurada en `.env`)

---

## 🚀 Instalación y ejecución

### 1. Clonar repositorio y entrar en la carpeta raíz
```bash
cd yahoo-llm-eval
```

### 2. Activar entorno virtual de Python
```bash
python -m venv venv
source venv/bin/activate    # Linux/Mac
venv\Scripts\activate     # Windows
```

Instalar dependencias si deseas ejecutar módulos locales:
```bash
pip install -r requirements.txt
```

### 3. Construir y levantar los servicios
```bash
docker compose up -d --build
```

### 4. Cargar los datos al sistema
```bash
docker compose run --rm load_data
```

### 5. Generar tráfico simulado
```bash
docker compose run --rm traffic
```

---

## 📊 Flujo de trabajo

1. **Carga de datos** → `load_data` importa el `train.csv` a la base del sistema.  
2. **Proxy LLM** → `llm_proxy` maneja la conexión al modelo (Gemini).  
3. **Generador de tráfico** → `traffic_generator` simula peticiones de usuarios.  
4. **Score** → `score` mide la similitud de respuestas (TF-IDF y métricas).  

---

## 🔑 Variables de entorno

El archivo `.env` debe contener:
```env
GEMINI_API_KEY=key correspondiente a usuario
```

---

## 🛑 Detener servicios
```bash
docker compose down
```

---

## ✨ Notas
- El sistema está pensado para entornos con recursos limitados, por lo que es recomendable ejecutar tráfico en lotes pequeños.  
- Puedes modificar los parámetros de tráfico en `traffic_generator` para ajustar la intensidad de consultas.  
