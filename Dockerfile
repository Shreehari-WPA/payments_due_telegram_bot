FROM python:3.14-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    tzdata \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app/ ./app/

RUN mkdir -p /app/data

# SQLite file lives in /app/data by default so it survives container recreation
# when /app/data is mounted as a volume. Override DATABASE_URL for PostgreSQL.
ENV DATABASE_URL=sqlite:////app/data/reminder_bot.db

CMD ["python", "-m", "app.main"]
