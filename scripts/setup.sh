#!/usr/bin/env bash
# Первичная установка бота: задаёт имя бота (обязательно),
# создаёт config.yaml и включает его в docker-compose.
set -euo pipefail
cd "$(dirname "$0")/.."

CONFIG="config.yaml"
COMPOSE_FILE="docker/docker-compose.yml"

echo "=== Установка бота для записи встреч Jitsi ==="
echo
printf "Введите имя бота (так оно будет видно в встрече): "
read -r raw_name
name="$(printf '%s' "$raw_name" | sed -e 's/^[[:space:]]*//' -e 's/[[:space:]]*$//')"
if [ -z "$name" ]; then
  echo "Ошибка: имя бота не может быть пустым." >&2
  exit 1
fi

# Всегда добавляем « AI» в конце (если его ещё нет).
last_word="$(printf '%s' "$name" | awk '{print tolower($NF)}')"
if [ "$last_word" != "ai" ]; then
  name="${name} AI"
fi

# 1) Конфигурация: создаём из шаблона и прописываем имя.
if [ ! -f "$CONFIG" ]; then
  cp config.example.yaml "$CONFIG"
  echo "Создан ${CONFIG} из config.example.yaml."
fi

tmp="$(mktemp)"
if grep -q '^default_bot_name:' "$CONFIG"; then
  awk -v name="$name" '
    /^default_bot_name:/ { print "default_bot_name: \"" name "\""; next }
    { print }
  ' "$CONFIG" > "$tmp"
else
  cat "$CONFIG" > "$tmp"
  printf '\ndefault_bot_name: "%s"\n' "$name" >> "$tmp"
fi
mv "$tmp" "$CONFIG"

# 2) Включаем проброс config.yaml в docker-compose (раскомментируем строку).
if grep -qE '^[[:space:]]*#[[:space:]]*-[[:space:]]+\.\./config\.yaml:/app/config\.yaml:ro' "$COMPOSE_FILE"; then
  tmp="$(mktemp)"
  sed -E 's|^([[:space:]]*)#[[:space:]]*(-[[:space:]]+\.\./config\.yaml:/app/config\.yaml:ro)$|\1\2|' \
    "$COMPOSE_FILE" > "$tmp"
  mv "$tmp" "$COMPOSE_FILE"
  echo "docker/docker-compose.yml: включён проброс config.yaml."
elif grep -qE '^[[:space:]]*-[[:space:]]+\.\./config\.yaml:/app/config\.yaml:ro' "$COMPOSE_FILE"; then
  echo "docker/docker-compose.yml: config.yaml уже проброшен."
else
  echo "Внимание: не нашёл строку проброса config.yaml в ${COMPOSE_FILE} —" >&2
  echo "добавьте вручную:  - ../config.yaml:/app/config.yaml:ro" >&2
fi

echo
echo "Имя бота в встречах:  ${name}"
echo "Конфигурация:         ${CONFIG}"
echo
echo "Дальше:  make build && make up"
echo "Панель:  http://127.0.0.1:8080"
