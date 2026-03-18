# ============================================
# Gateway Dockerfile
# ============================================
FROM python:3.11-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

# Install dependencies
COPY requirements.txt .
RUN pip install -r requirements.txt

# Copy application code
COPY ./app /app/gateway/app

EXPOSE 18789

HEALTHCHECK --interval=30s --timeout=10s --start-period=10s --retries=3 \
  CMD python -c "import requests; r=requests.get('http://localhost:18789/health'); r.raise_for_status()" || exit 1

CMD ["uvicorn", "gateway.app.main:app", "--host", "0.0.0.0", "--port", "18789"]
