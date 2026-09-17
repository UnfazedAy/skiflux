FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    POETRY_VERSION=2.4.1 \
    POETRY_VIRTUALENVS_CREATE=false

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libpq-dev \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Install Poetry
RUN pip install --no-cache-dir poetry==$POETRY_VERSION

WORKDIR /app

# Install Python dependencies
COPY pyproject.toml poetry.lock ./

RUN poetry install --only main --no-root

# Copy project
COPY . .

# Create non-root user
RUN groupadd -r skiflux && \
    useradd -r -g skiflux -d /app -s /usr/sbin/nologin skiflux && \
    chown -R skiflux:skiflux /app

RUN chmod +x scripts/*.sh

USER skiflux

EXPOSE 8000

CMD ["./scripts/start.sh"]