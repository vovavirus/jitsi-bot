# Удобные команды для сборки и запуска бота через Docker Desktop.
# Требует: Docker Desktop запущен.

COMPOSE := docker compose -f docker/docker-compose.yml

.PHONY: setup build up down restart logs ps clean

setup: ## Первичная установка: задать имя бота, создать config.yaml
	./scripts/setup.sh

build: ## Собрать образ
	$(COMPOSE) build

up: ## Запустить контейнер в фоне
	@test -f config.yaml || { echo "Не найден config.yaml — сначала выполните 'make setup' (запросит имя бота)."; exit 1; }
	$(COMPOSE) up -d

down: ## Остановить и удалить контейнер
	$(COMPOSE) down

restart: down up

logs: ## Смотреть логи (Ctrl+C для выхода)
	$(COMPOSE) logs -f

ps: ## Статус контейнера
	$(COMPOSE) ps

clean: ## Остановить и удалить образ
	$(COMPOSE) down --rmi local
