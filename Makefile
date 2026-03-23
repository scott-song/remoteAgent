.PHONY: up down logs logs-rc logs-bot bot setup test

# Start Rocket.Chat + MongoDB
up:
	docker compose up -d

# Stop everything
down:
	docker compose down

# View all logs
logs:
	docker compose logs -f

# View Rocket.Chat logs
logs-rc:
	docker compose logs -f rocketchat

# Run bot locally (for development)
bot:
	cd bot && python -m bot.main

# Initial Python setup
setup:
	cd bot && python3 -m venv .venv && . .venv/bin/activate && pip install -e ".[dev]"

# Run tests
test:
	cd bot && python -m pytest tests/ -v
