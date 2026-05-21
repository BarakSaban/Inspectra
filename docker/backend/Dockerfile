# Backend production Dockerfile for Inspectra
# This image uses a small Python base, installs runtime dependencies,
# and runs the Flask application with Gunicorn for concurrency.

FROM python:3.12-slim AS base

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    APP_HOME=/app

WORKDIR ${APP_HOME}

# Install packages needed for building optional dependencies and runtime.
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Copy only dependency metadata first for better Docker layer caching.
COPY requirements.txt ./

# Install application dependencies and Gunicorn for production.
RUN pip install --no-cache-dir -r requirements.txt gunicorn psycopg2-binary

# Copy the Python application code into the image.
COPY . ${APP_HOME}

# Use a dedicated non-root user for better security.
RUN useradd --create-home --shell /bin/bash inspectra && chown -R inspectra:inspectra ${APP_HOME}
USER inspectra

EXPOSE 5000

# Healthcheck probes should hit the application health endpoint.
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
  CMD curl -f http://127.0.0.1:5000/healthz || exit 1

# Use Gunicorn for production concurrency.
CMD ["gunicorn", "-w", "4", "-k", "gthread", "--threads", "4", "-b", "0.0.0.0:5000", "run:app"]
