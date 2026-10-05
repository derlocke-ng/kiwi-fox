.PHONY: run gui images test leak lint fmt engine setup
# Prefer the project venv when present (pytest/ruff live there; PyGObject comes
# from system site-packages, per the tech-stack rule).
PY := $(shell [ -x .venv/bin/python ] && echo .venv/bin/python || echo python3)
export PYTHONPATH := src:.

setup:
	python3 -m venv --system-site-packages .venv
	.venv/bin/python -m pip install -q --upgrade pip
	.venv/bin/python -m pip install -q pydantic pytest ruff

run:
	$(PY) -m kiwi_fox $(ARGS)

gui:
	$(PY) -m kiwi_fox.ui

engine:
	$(PY) -m kiwi_fox engine fetch

images:
	podman build -t kiwi-fox/gateway:latest -f containers/gateway/Containerfile containers/gateway
	podman build -t kiwi-fox/browser:latest -f containers/browser/Containerfile containers/browser

test:
	$(PY) -m pytest tests/unit -q

leak:
	$(PY) -m pytest tests/leak -q $(ARGS)

lint:
	.venv/bin/ruff check src tests containers tools
	.venv/bin/ruff format --check src tests containers tools

fmt:
	.venv/bin/ruff format src tests containers tools
	.venv/bin/ruff check --fix src tests containers tools
