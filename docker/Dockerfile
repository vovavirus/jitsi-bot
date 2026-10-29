# Бот для записи встреч Jitsi.
# Основан на официальном Playwright-образе (Chromium + зависимости браузера),
# поверх которого ставятся Xvfb, PulseAudio и FFmpeg.
#
# Целевая архитектура: arm64 (Apple Silicon). amd64 соберётся через Rosetta.

FROM mcr.microsoft.com/playwright/python:v1.48.0

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# PulseAudio отказывается работать от root, поэтому всё приложение
# (Xvfb, PulseAudio, Chromium, FFmpeg, Python) запускается от непривилегированного
# пользователя. Базовый Playwright-образ уже содержит пользователя с UID/GID 1000
# (pwuser) — используем его, все компоненты должны быть под одним пользователем,
# чтобы иметь доступ к X-дисплею и сокету PulseAudio.

RUN apt-get update && apt-get install -y --no-install-recommends \
      xvfb \
      x11-xserver-utils \
      x11-utils \
      pulseaudio \
      pulseaudio-utils \
      ffmpeg \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

COPY --chown=1000:1000 app/ /app/app/
COPY --chown=1000:1000 config.example.yaml /app/config.example.yaml
COPY --chown=1000:1000 docker/entrypoint.sh /app/entrypoint.sh
# /run принадлежит root'у, а приложение работает от uid 1000 — каталоги
# сокетов PulseAudio для слотов (pulse1..pulse8) создаём заранее.
RUN chmod +x /app/entrypoint.sh \
    && mkdir -p /app/recordings && chown 1000:1000 /app/recordings \
    && mkdir -p /run/pulse /run/pulse1 /run/pulse2 /run/pulse3 \
    && mkdir -p /run/pulse4 /run/pulse5 /run/pulse6 /run/pulse7 /run/pulse8 \
    && chown 1000:1000 /run/pulse /run/pulse1 /run/pulse2 /run/pulse3 \
    && chown 1000:1000 /run/pulse4 /run/pulse5 /run/pulse6 /run/pulse7 /run/pulse8

USER 1000
EXPOSE 8080

ENTRYPOINT ["/app/entrypoint.sh"]
