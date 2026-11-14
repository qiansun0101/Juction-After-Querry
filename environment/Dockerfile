FROM ubuntu:24.04

RUN apt-get update \
    && apt-get install -y --no-install-recommends python3 curl ca-certificates \
    && rm -rf /var/lib/apt/lists/*

COPY client/chess /usr/local/bin/chess
RUN chmod 755 /usr/local/bin/chess

WORKDIR /app
