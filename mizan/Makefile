PY := $(shell [ -x .venv/bin/python ] && echo .venv/bin/python || echo python3)
TODAY := 2026-12-01

.PHONY: demo demo-deterministic test install venv

venv:
	python3 -m venv .venv && .venv/bin/pip install -q anthropic

install:
	pip install -e ".[agents]"

# The evidence test, justified demand and the recoverable ceiling. No API key.
demo-deterministic:
	PYTHONPATH=src $(PY) -m mizan.cli examples/units.csv --no-agents \
		--today $(TODAY) -o review.csv

# Full pass: explain the position, draft the claim, review, gate.
# Needs ANTHROPIC_API_KEY.
demo:
	PYTHONPATH=src $(PY) -m mizan.cli examples/units.csv \
		--today $(TODAY) -o review.csv

test:
	PYTHONPATH=src $(PY) tests/test_mizan.py
	PYTHONPATH=src $(PY) tests/test_agents.py
	PYTHONPATH=src $(PY) tests/check_review.py
