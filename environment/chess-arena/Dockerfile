FROM ubuntu:24.04

RUN apt-get update \
    && apt-get install -y --no-install-recommends python3 python3-venv stockfish \
    && rm -rf /var/lib/apt/lists/*

RUN python3 -m venv /opt/venv \
    && /opt/venv/bin/pip install --no-cache-dir chess==1.11.2 fastmcp==4.2.0

WORKDIR /srv
COPY arena.py server.py ./
COPY web ./web
RUN mkdir -p /data

ENV STOCKFISH_PATH=/usr/games/stockfish PYTHONUNBUFFERED=1
EXPOSE 8000
CMD ["/opt/venv/bin/python", "server.py"]
