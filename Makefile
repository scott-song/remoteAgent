.PHONY: bot setup test

# Run bot
bot:
	cd bot && .venv/bin/python -m bot.main

# Initial setup
setup:
	cd bot && python3 -m venv .venv && . .venv/bin/activate && pip install -e ".[dev]"

# Run tests
test:
	cd bot && .venv/bin/python -m pytest tests/ -v
