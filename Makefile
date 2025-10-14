# Makefile for FastAPI project (with optional Docker)

# ----------------------------
# Variables
# ----------------------------
IMAGE_NAME=orinai-wa-report-app
PORT=8000
CONTAINER_NAME=orinai-wa-report-container
USE_DOCKER ?= false

# Python virtual environment settings (for non-Docker runs)
VENV_DIR=.venv
PYTHON=$(VENV_DIR)/bin/python
PIP=$(VENV_DIR)/bin/pip

.PHONY: build run stop remove logs shell rebuild restart test clean clean-cache venv

# ----------------------------
# Docker targets
# ----------------------------

docker-build:
	docker build -t $(IMAGE_NAME) .

docker-run:
	# Stop and remove any existing container with the same name before running a new one
	-docker stop $(CONTAINER_NAME) 2>/dev/null || true
	-docker rm $(CONTAINER_NAME) 2>/dev/null || true
	docker run -d --env-file .env -p $(PORT):$(PORT) --name $(CONTAINER_NAME) $(IMAGE_NAME)

docker-stop:
	-docker stop $(CONTAINER_NAME)

docker-remove:
	-docker rm $(CONTAINER_NAME)

docker-logs:
	docker logs -f $(CONTAINER_NAME)

docker-shell:
	docker exec -it $(CONTAINER_NAME) /bin/sh

# ----------------------------
# Local (non-Docker) targets
# ----------------------------

venv:
	python3 -m venv $(VENV_DIR)
	$(PIP) install --upgrade pip
	$(PIP) install -r requirements.txt

local-run:
	$(PYTHON) -m src.orin_wa_report.main

local-test:
	$(PYTHON) -m pytest tests/

clean:
	rm -rf $(VENV_DIR) __pycache__ .pytest_cache

clean-cache:
	docker builder prune -f

# ----------------------------
# Conditional (Unified) targets
# ----------------------------

build:
ifeq ($(USE_DOCKER),true)
	$(MAKE) docker-build
else
	$(MAKE) venv
endif

run:
ifeq ($(USE_DOCKER),true)
	$(MAKE) docker-run
else
	$(MAKE) local-run
endif

stop:
ifeq ($(USE_DOCKER),true)
	$(MAKE) docker-stop
endif

remove:
ifeq ($(USE_DOCKER),true)
	$(MAKE) docker-remove
endif

logs:
ifeq ($(USE_DOCKER),true)
	$(MAKE) docker-logs
endif

shell:
ifeq ($(USE_DOCKER),true)
	$(MAKE) docker-shell
endif

rebuild:
	$(MAKE) stop
	$(MAKE) remove
	$(MAKE) build
	$(MAKE) run

restart:
	$(MAKE) stop
	$(MAKE) remove
	$(MAKE) run

test:
ifeq ($(USE_DOCKER),true)
	docker exec -it $(CONTAINER_NAME) pytest tests/
else
	$(MAKE) local-test
endif
