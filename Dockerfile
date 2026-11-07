# Railway-ready Python web service
FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# Node.js is required for JavaScript bot projects; bash/procps support runtime tools.
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc g++ make curl git nodejs npm bash procps \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt ./requirements.txt
RUN python -m pip install --upgrade pip && python -m pip install -r requirements.txt

COPY . .
RUN mkdir -p /app/uploads /app/_temp_zips

EXPOSE 8080

# Railway supplies PORT at runtime; keep one web worker to avoid duplicate bot restorations.
CMD ["sh", "-c", "exec gunicorn --bind 0.0.0.0:${PORT:-8080} --workers 1 --worker-class gthread --threads 2 --timeout 180 --graceful-timeout 30 --keep-alive 5 --max-requests 1000 --max-requests-jitter 100 --access-logfile - --error-logfile - app:app"]
