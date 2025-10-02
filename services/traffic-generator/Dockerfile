FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .

RUN pip install --no-cache-dir -r requirements.txt

# Copiamos código y datos
COPY services/traffic-generator/ .

# Ejecutar generador de tráfico automáticamente
CMD ["python", "traffic_generator.py"]
