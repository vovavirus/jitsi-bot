#!/usr/bin/env bash
# Точка входа контейнера: поднимает изолированное окружение
# (PulseAudio + Xvfb), затем запускает веб-приложение.
set -euo pipefail

# --- Настройки окружения ---
XDG_DIR=/tmp/xdg-runtime
mkdir -p "${XDG_DIR}" && chmod 700 "${XDG_DIR}"
export XDG_RUNTIME_DIR="${XDG_DIR}"

PULSE_SOCKET="${PULSE_SOCKET:-/run/pulse/native}"
PULSE_SINK="${PULSE_SINK:-botsink}"
X_DISPLAY="${DISPLAY:-:99}"

mkdir -p /run/pulse
export PULSE_RUNTIME_PATH=/run/pulse
export PULSE_SERVER="unix:${PULSE_SOCKET}"
export DISPLAY="${X_DISPLAY}"

# --- 1) PulseAudio (не daemonize, держим на переднем плане в фоне) ---
pulseaudio --daemonize=no --exit-idle-time=-1 --log-target=stderr --log-level=warn &
PULSE_PID=$!

# Ждём появления сокета.
for _ in $(seq 1 50); do
  if [ -S "${PULSE_SOCKET}" ]; then
    break
  fi
  sleep 0.2
done

# --- 2) Создаём виртуальный sink для захвата и делаем его дефолтным ---
# Весь звук браузера попадает в этот sink, а захват ведётся с его monitor-источника.
pactl load-module module-null-sink "sink_name=${PULSE_SINK}" "sink_properties=device.description=BotCaptureSink"
pactl set-default-sink "${PULSE_SINK}" || true

# --- 3) Xvfb: виртуальный экран для окна браузера ---
Xvfb "${X_DISPLAY}" -screen 0 1920x1080x24 -nolisten tcp &
XVFB_PID=$!
sleep 1

# --- Обработка корректного завершения ---
shutdown() {
  echo "entrypoint: shutting down child processes..."
  kill "${XVFB_PID}" 2>/dev/null || true
  kill "${PULSE_PID}" 2>/dev/null || true
  wait 2>/dev/null || true
}
trap shutdown INT TERM

# --- 4) Веб-приложение (exec — получает сигналы напрямую) ---
exec python -m uvicorn app.main:app \
  --host 0.0.0.0 --port "${PORT:-8080}" \
  --log-level "${UVICORN_LOG_LEVEL:-info}"
