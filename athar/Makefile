PY := $(shell [ -x .venv/bin/python ] && echo .venv/bin/python || echo python3)
TODAY := 2026-09-22

.PHONY: demo demo-deterministic test install venv

venv:
	python3 -m venv .venv && .venv/bin/pip install -q anthropic

install:
	pip install -e ".[agents]"

# The custody join, the dispute clock and the evidence check. No API key, no
# model calls. --today pins the run so the output is reproducible.
demo-deterministic:
	PYTHONPATH=src $(PY) -m athar.cli examples/fines.csv --no-agents \
		--today $(TODAY) --show-all -o attributions.csv

# Full pass: explain the attributions, draft the actions, review, gate.
# Needs ANTHROPIC_API_KEY.
demo:
	PYTHONPATH=src $(PY) -m athar.cli examples/fines.csv \
		--today $(TODAY) -o attributions.csv

test:
	PYTHONPATH=src $(PY) tests/test_athar.py
	PYTHONPATH=src $(PY) tests/test_agents.py
	PYTHONPATH=src $(PY) tests/check_attributions.py
