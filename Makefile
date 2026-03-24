.PHONY: coder hr setup test test-core test-coder test-hr run-coder run-hr

# Run coder bot (logs to bot.log)
coder:
	.venv/bin/python -u -m coder.main 2>&1 | tee bot.log

# Run HR bot (logs to bot.log)
hr:
	.venv/bin/python -u -m hr.main 2>&1 | tee bot.log

# Setup + run coder bot (logs to bot.log)
run-coder: setup
	.venv/bin/python -u -m coder.main 2>&1 | tee bot.log

# Setup + run HR bot (logs to bot.log)
run-hr: setup
	.venv/bin/python -u -m hr.main 2>&1 | tee bot.log

# Initial setup — single shared venv
setup:
	python3.12 -m venv .venv
	.venv/bin/pip install --upgrade pip
	.venv/bin/pip install -e "core[dev]" -e "bots/coder[dev]" -e "bots/hr[dev]"

# Run all tests
test:
	.venv/bin/python -m pytest core/tests/ bots/coder/tests/ bots/hr/tests/ -v

# Per-package tests
test-core:
	.venv/bin/python -m pytest core/tests/ -v

test-coder:
	.venv/bin/python -m pytest bots/coder/tests/ -v

test-hr:
	.venv/bin/python -m pytest bots/hr/tests/ -v
