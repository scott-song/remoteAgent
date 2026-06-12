.PHONY: coder hr setup test test-core test-coder test-hr run-coder run-hr lint format typecheck lock

# First available python3 interpreter that is >= 3.10 (the system python3 may be older).
PYTHON := $(shell for p in python3.12 python3.11 python3.10 python3; do if command -v $$p >/dev/null 2>&1 && $$p -c 'import sys; sys.exit(0 if sys.version_info[:2] >= (3, 10) else 1)' 2>/dev/null; then echo $$p; break; fi; done)

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

# Initial setup — single shared venv (requires Python 3.10+)
setup:
	@test -n "$(PYTHON)" || { echo "Python 3.10+ is required"; exit 1; }
	$(PYTHON) -m venv .venv
	.venv/bin/pip install --upgrade pip
	.venv/bin/pip install -e "core[dev]" -e "bots/coder[dev]" -e "bots/hr[dev]" ruff mypy pytest-cov pre-commit pip-tools
	.venv/bin/pre-commit install

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

# Lint (ruff)
lint:
	.venv/bin/ruff check core bots

# Auto-format + autofix (ruff)
format:
	.venv/bin/ruff format core bots
	.venv/bin/ruff check --fix core bots

# Type-check (mypy, gradual mode)
typecheck:
	.venv/bin/mypy core bots

# Regenerate the dependency lockfile from the current venv
lock:
	.venv/bin/pip freeze --exclude-editable > requirements.lock
