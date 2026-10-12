PY := $(shell [ -x .venv/bin/python ] && echo .venv/bin/python || echo python3)
TODAY := 2026-11-01

.PHONY: demo demo-deterministic test install venv

venv:
	python3 -m venv .venv && .venv/bin/pip install -q anthropic

install:
	pip install -e ".[agents]"

# The double projection, the runway and the exposure. No API key, no model
# calls. --today is pinned past the 2026 runway so BREACH_LOCKED is visible.
demo-deterministic:
	PYTHONPATH=src $(PY) -m ufuq.cli examples/roster.csv --no-agents \
		--today $(TODAY) -o projections.csv

# Full pass: explain the position, draft the plan, review, gate.
# Needs ANTHROPIC_API_KEY.
demo:
	PYTHONPATH=src $(PY) -m ufuq.cli examples/roster.csv \
		--today $(TODAY) -o projections.csv

test:
	PYTHONPATH=src $(PY) tests/test_ufuq.py
	PYTHONPATH=src $(PY) tests/test_agents.py
	PYTHONPATH=src $(PY) tests/check_projections.py
