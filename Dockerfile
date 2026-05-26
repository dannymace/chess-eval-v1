FROM python:3.12-slim

ARG VERSION=1.0.2

LABEL org.opencontainers.image.title="chess-eval-v1" \
      org.opencontainers.image.description="Dockerized Chess.com game review with local Stockfish analysis" \
      org.opencontainers.image.version="${VERSION}" \
      org.opencontainers.image.source="https://github.com/dannymace/chess-eval-v1"

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV STOCKFISH_PATH=/usr/games/stockfish
ENV CHESS_EVAL_REPORT_DIR=/reports

RUN apt-get update \
    && apt-get install -y --no-install-recommends stockfish \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
RUN mkdir -p /reports

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app

VOLUME ["/reports"]

ENTRYPOINT ["python", "-m", "app"]
