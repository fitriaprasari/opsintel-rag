FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    curl \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# Install the shared ai-orchestrator package (provides app.*)
COPY ../ai-orchestrator/pyproject.toml /tmp/orchestrator-pyproject.toml
COPY ../ai-orchestrator/app/ /shared/app/
ENV PYTHONPATH=/shared

COPY pyproject.toml ./
RUN pip install --upgrade pip && pip install -e ".[dev]"

COPY app/ ./app/

EXPOSE 8001

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8001", "--reload"]
