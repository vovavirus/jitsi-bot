#!/usr/bin/env bash
# Точка входа контейнера: поднимает изолированное окружение
# (N x PulseAudio + N x Xvfb + N x sink), затем запускает веб-приложение.
#
# Каждой одновременной записи (слоту i) достаётся:
#   - Xvfb на дисплее :<BASE+i>
#   - собственный инстанс PulseAudio с сокетоми /run/pulse<i>/native
#   - null-sink <PULSE_SINK><i> (и .monitor для захвата)
set -euo pipefail

# --- Настройки окружения ---
XDG_DIR=/tmp/xdg-runtime
mkdir -p "${XDG_DIR}" && chmod 700 "${XDG_DIR}"
export XDG_RUNTIME_DIR="${XDG_DIR}"

PULSE_SOCKET="${PULSE_SOCKET:-/run/pulse/native}"
PULSE_SINK="${PULSE_SINK:-botsink}"
X_DISPLAY="${DISPLAY:-:99}"
MAX_CONCURRENT="${MAX_CONCURRENT_RECORDINGS:-3}"

export DISPLAY="${X_DISPLAY}"

# Номер базового X-дисплея: ":99" -> 99
DISP_NUM="${X_DISPLAY#:}"
case "${DISP_NUM}" in (*[!0-9]*|'') DISP_NUM=99;; esac

PULSE_PIDS=()
XVFB_PIDS=()

# --- 1) PulseAudio-инстансы и sink'и по числу слотов ---
for i in $(seq 0 $((MAX_CONCURRENT - 1))); do
  if [ "${i}" -eq 0 ]; then
    P_DIR="/run/pulse"
    P_SOCK="${PULSE_SOCKET}"
    SINK="${PULSE_SINK}"
  else
    P_DIR="/run/pulse${i}"
    P_SOCK="/run/pulse${i}/native"
    SINK="${PULSE_SINK}${i}"
  fi

  mkdir -p "${P_DIR}"
  PULSE_RUNTIME_PATH="${P_DIR}" pulseaudio --daemonize=no --exit-idle-time=-1 \
    --log-target=stderr --log-level=warn &
  PULSE_PIDS+=($!)

  # Ждём появления сокета инстанса.
  for _ in $(seq 1 50); do
    if [ -S "${P_SOCK}" ]; then break; fi
    sleep 0.2
  done

  # Виртуальный sink для захвата и дефолтный в этом инстансе:
  # весь звук браузера слота попадает в него, захват — с .monitor.
  PULSE_SERVER="unix:${P_SOCK}" pactl load-module module-null-sink \
    "sink_name=${SINK}" "sink_properties=device.description=BotCaptureSink${i}"
  PULSE_SERVER="unix:${P_SOCK}" pactl set-default-sink "${SINK}" || true
  echo "entrypoint: pulse instance ${i}: socket=${P_SOCK} sink=${SINK}"
done

# --- 2) Xvfb: по виртуальному экрану на слот ---
for i in $(seq 0 $((MAX_CONCURRENT - 1))); do
  D=$((DISP_NUM + i))
  Xvfb ":${D}" -screen 0 1920x1080x24 -nolisten tcp &
  XVFB_PIDS+=($!)
  echo "entrypoint: Xvfb :${D} (slot ${i})"
done
sleep 1

# --- Обработка корректного завершения ---
shutdown() {
  echo "entrypoint: shutting down child processes..."
  for pid in "${XVFB_PIDS[@]}" "${PULSE_PIDS[@]}"; do
    kill "${pid}" 2>/dev/null || true
  done
  wait 2>/dev/null || true
}
trap shutdown INT TERM

# --- 3) Веб-приложение (exec — получает сигналы напрямую) ---
exec python -m uvicorn app.main:app \
  --host 0.0.0.0 --port "${PORT:-8080}" \
  --log-level "${UVICORN_LOG_LEVEL:-info}"
