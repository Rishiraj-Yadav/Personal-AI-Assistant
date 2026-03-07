# ============================================
# Optimized Backend Dockerfile for SonarBot
# ============================================

FROM python:3.11-slim

WORKDIR /app

# ============================================
# Environment variables
# ============================================
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_DEFAULT_TIMEOUT=300 \
    PLAYWRIGHT_BROWSERS_PATH=/opt/pw-browsers

# ============================================
# Install system dependencies (minimal) + Playwright deps
# Using --no-install-recommends to keep image small
# ============================================
RUN apt-get update && apt-get install -y --no-install-recommends \
    sqlite3 \
    curl \
    # Playwright/Chromium runtime dependencies
    libnss3 \
    libnspr4 \
    libdbus-1-3 \
    libatk1.0-0 \
    libatk-bridge2.0-0 \
    libcups2 \
    libdrm2 \
    libxkbcommon0 \
    libxcomposite1 \
    libxdamage1 \
    libxfixes3 \
    libxrandr2 \
    libgbm1 \
    libasound2 \
    libpango-1.0-0 \
    libcairo2 \
    fonts-liberation \
    && rm -rf /var/lib/apt/lists/*

# ============================================
# Install PyTorch CPU-only FIRST (separate layer for caching)
# This avoids downloading ~3.5 GB of NVIDIA CUDA packages
# ============================================
RUN pip install torch --index-url https://download.pytorch.org/whl/cpu

# ============================================
# Install remaining Python packages
# ============================================
COPY requirements.txt .
RUN pip install -r requirements.txt

# ============================================
# Install ONLY Chromium for Playwright
# ============================================
RUN playwright install chromium

# ============================================
# Copy application code
# ============================================
COPY ./app /app/app
COPY ./skills /app/skills

RUN chmod +x /app/skills/*/*.py
RUN mkdir -p /app/logs /app/data

# ============================================
# Pre-download sentence-transformers model
# ============================================
RUN python -c "from sentence_transformers import SentenceTransformer; SentenceTransformer('all-MiniLM-L6-v2')"

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=3 \
  CMD python -c "import requests; requests.get('http://localhost:8000/api/v1/health')" || exit 1

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
#     rm -rf /root/.cache/ms-playwright

# # Copy application code
# COPY ./app /app/app
# COPY ./skills /app/skills

# # Set permissions
# RUN chmod +x /app/skills/*/*.py

# # Create directories
# RUN mkdir -p /app/logs /app/data

# EXPOSE 8000

# HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=3 \
#   CMD python -c "import requests; requests.get('http://localhost:8000/api/v1/health')" || exit 1

# CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
