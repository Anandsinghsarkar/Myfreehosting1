# REAL_NAME: Dockerfile
FROM python:3.11-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc g++ make curl git nodejs npm bash procps \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

COPY requirements.txt .
RUN pip install --upgrade pip && pip install -r requirements.txt

COPY . .

RUN mkdir -p /app/uploads /app/_temp_zips

EXPOSE 8080

# Note: --timeout 300 for terminal commands
CMD gunicorn -w 1 --threads 4 --timeout 300 --log-level debug -b 0.0.0.0:$PORT app:app
