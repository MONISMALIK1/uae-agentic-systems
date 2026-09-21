PY := $(shell [ -x .venv/bin/python ] && echo .venv/bin/python || echo python3)
TODAY := 2026-09-21

.PHONY: demo demo-deterministic test install venv

venv:
	python3 -m venv .venv && .venv/bin/pip install -q anthropic

install:
	pip install -e ".[agents]"

# Prerequisite checks, critical path and forecast dates. No API key, no model
# calls. --today pins the run so the output is reproducible from the fixture.
demo-deterministic:
	PYTHONPATH=src $(PY) -m masar.cli examples/projects.csv --no-agents \
		--today $(TODAY) -o schedule.csv

# Full pass: explain the position, draft the actions, review, gate.
# Needs ANTHROPIC_API_KEY.
demo:
	PYTHONPATH=src $(PY) -m masar.cli examples/projects.csv \
		--today $(TODAY) -o schedule.csv

test:
	PYTHONPATH=src $(PY) tests/test_masar.py
	PYTHONPATH=src $(PY) tests/test_agents.py
	PYTHONPATH=src $(PY) tests/check_schedule.py
