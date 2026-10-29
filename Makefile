# Удобные команды для сборки и запуска бота через Docker Desktop.
# Требует: Docker Desktop запущен.

COMPOSE := docker compose -f docker/docker-compose.yml

.PHONY: build up down restart logs ps clean

build: ## Собрать образ
	$(COMPOSE) build

up: ## Запустить контейнер в фоне
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
