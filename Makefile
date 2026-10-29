.PHONY: run gui images test leak lint fmt engine setup
# Prefer the project venv when present (pytest/ruff live there; PyGObject comes
# from system site-packages, per the tech-stack rule).
PY := $(shell [ -x .venv/bin/python ] && echo .venv/bin/python || echo python3)
# kiwi-proxy (the gateway, providers, DNS) from a sibling checkout; the tests
# find it themselves (tests/conftest.py).
KIWI_PROXY_SRC ?= ../kiwi-proxy/src
export PYTHONPATH := src:.:$(KIWI_PROXY_SRC)

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

# The gateway image is kiwi-proxy's: `make -C ../kiwi-proxy images`.
images:
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
