FROM python:3.14-slim

# uv для быстрой установки зависимостей
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

WORKDIR /app

# Системные зависимости
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# Копируем lock-файл и манифест отдельно для кэша слоёв
COPY pyproject.toml uv.lock* ./
RUN uv sync --frozen --no-install-project --no-dev

# Копируем код
COPY . .
RUN uv sync --frozen --no-dev

# Не root
RUN useradd -m -u 1000 wotk && chown -R wotk:wotk /app
USER wotk

EXPOSE 8000

CMD ["uv", "run", "uvicorn", "wotk.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
