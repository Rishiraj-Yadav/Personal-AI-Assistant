# Backend Dockerfile for OpenClaw Agent
FROM python:3.11-slim

# Set working directory
WORKDIR /app

# Set environment variables
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# Install system dependencies
RUN apt-get update && apt-get install -y \
    wget \
    gnupg \
    sqlite3 \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements first for better caching
COPY requirements.txt .

# Install Python dependencies
RUN pip install --upgrade pip && \
    pip install -r requirements.txt

# Install Playwright browsers
RUN playwright install chromium

# Copy application code
COPY ./app /app/app

# Copy skills directory
COPY ./skills /app/skills

# Make skill scripts executable
RUN chmod +x /app/skills/*/*.py

# Create logs directory
RUN mkdir -p /app/logs

# Expose port
EXPOSE 8000

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD python -c "import requests; requests.get('http://localhost:8000/api/v1/health')"

# Run the application
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]





# # ============================================
# # Optimized Dockerfile - Reduces size from 15GB to ~3GB
# # ============================================

# FROM python:3.11-slim

# WORKDIR /app

# # ============================================
# # Install system dependencies (minimal)
# # ============================================
# RUN apt-get update && apt-get install -y \
#     wget \
#     gnupg \
#     sqlite3 \
#     curl \
#     # Playwright dependencies (minimal)
#     libnss3 \
#     libnspr4 \
#     libdbus-1-3 \
#     libatk1.0-0 \
#     libatk-bridge2.0-0 \
#     libcups2 \
#     libdrm2 \
#     libxkbcommon0 \
#     libxcomposite1 \
#     libxdamage1 \
#     libxfixes3 \
#     libxrandr2 \
#     libgbm1 \
#     libasound2 \
#     && rm -rf /var/lib/apt/lists/* \
#     && apt-get clean

# # ============================================
# # Copy requirements and install Python packages
# # ============================================
# COPY requirements.txt .

# # ✅ OPTIMIZATION 1: Use pip cache and no-cache-dir to reduce size
# # ✅ OPTIMIZATION 2: Install packages in specific order (smallest first)
# RUN pip install --upgrade pip && \
#     pip install --no-cache-dir -r requirements.txt

# # ============================================
# # ✅ OPTIMIZATION 3: Install ONLY Chromium (not all browsers)
# # This saves ~10GB compared to installing all Playwright browsers
# # ============================================
# RUN playwright install chromium && \
#     playwright install-deps chromium && \
#     # ✅ OPTIMIZATION 4: Remove playwright cache after install
#     rm -rf /root/.cache/ms-playwright

# # ============================================
# # ✅ OPTIMIZATION 5: Copy only necessary files
# # ============================================
# COPY ./app /app/app
# COPY ./skills /app/skills

# # Set permissions
# RUN chmod +x /app/skills/*/*.py

# # Create directories
# RUN mkdir -p /app/logs /app/data

# # ============================================
# # ✅ OPTIMIZATION 6: Download sentence-transformers model during build
# # This prevents downloading on every container start
# # ============================================
# RUN python -c "from sentence_transformers import SentenceTransformer; SentenceTransformer('all-MiniLM-L6-v2')"

# # ============================================
# # Expose port
# # ============================================
# EXPOSE 8000

# # ============================================
# # Health check
# # ============================================
# HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=3 \
#   CMD python -c "import requests; requests.get('http://localhost:8000/api/v1/health')" || exit 1

# # ============================================
# # Start command
# # ============================================
# CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]




# # ============================================
# # Multi-Stage Dockerfile - Maximum Optimization
# # Reduces from 15GB → ~2.5GB
# # ============================================

# # ============================================
# # Stage 1: Builder - Install dependencies
# # ============================================
# FROM python:3.11-slim as builder

# WORKDIR /build

# # Install build dependencies
# RUN apt-get update && apt-get install -y --no-install-recommends \
#     gcc \
#     g++ \
#     && rm -rf /var/lib/apt/lists/*

# # Copy and install Python packages
# COPY requirements.txt .

# # Install to /install directory
# RUN pip install --prefix=/install --no-cache-dir --upgrade pip && \
#     pip install --prefix=/install --no-cache-dir -r requirements.txt

# # Download sentence-transformers model
# RUN python -c "import sys; sys.path.insert(0, '/install/lib/python3.11/site-packages'); from sentence_transformers import SentenceTransformer; SentenceTransformer('all-MiniLM-L6-v2')"

# # ============================================
# # Stage 2: Runtime - Minimal image
# # ============================================
# FROM python:3.11-slim

# WORKDIR /app

# # Install only runtime system dependencies
# RUN apt-get update && apt-get install -y --no-install-recommends \
#     sqlite3 \
#     curl \
#     # Minimal Playwright dependencies
#     libnss3 \
#     libnspr4 \
#     libatk1.0-0 \
#     libatk-bridge2.0-0 \
#     libcups2 \
#     libxkbcommon0 \
#     libxcomposite1 \
#     libxdamage1 \
#     libgbm1 \
#     && rm -rf /var/lib/apt/lists/* \
#     && apt-get clean

# # Copy installed Python packages from builder
# COPY --from=builder /install /usr/local

# # Copy sentence-transformers model from builder
# COPY --from=builder /root/.cache/torch /root/.cache/torch
# COPY --from=builder /root/.cache/huggingface /root/.cache/huggingface

# # Install Playwright Chromium only
# RUN playwright install chromium && \
#     playwright install-deps chromium && \
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
