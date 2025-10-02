FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .

RUN pip install --no-cache-dir -r requirements.txt

COPY services/traffic-generator/ .

CMD ["python", "traffic_generator.py"]
