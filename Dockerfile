# ============================================
# A7 HOSTING — Docker Image
# ============================================
FROM python:3.11-slim

# System dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    g++ \
    make \
    curl \
    git \
    nodejs \
    npm \
    && rm -rf /var/lib/apt/lists/*

# Working directory
WORKDIR /app

# Environment
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# Install Python deps first (docker cache)
COPY requirements.txt .
RUN pip install --upgrade pip && \
    pip install -r requirements.txt

# Copy rest of the app
COPY . .

# Create uploads folder
RUN mkdir -p /app/uploads

# Expose port
EXPOSE 8080

# Start command
CMD gunicorn -w 1 --threads 4 -b 0.0.0.0:$PORT app:app
