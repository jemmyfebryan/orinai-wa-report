# Makefile for FastAPI Docker project

# Variables
IMAGE_NAME=orinai-wa-report-app
PORT=8000
CONTAINER_NAME=orinai-wa-report-container

.PHONY: build run stop remove logs shell

# Build Docker image
build:
	docker build -t $(IMAGE_NAME) .

# Run the container (detached)
run:
	docker run -d --env-file .env -p $(PORT):$(PORT) --name $(CONTAINER_NAME) $(IMAGE_NAME)

# Stop the container
stop:
	docker stop $(CONTAINER_NAME)

# Remove the container
remove:
	docker rm $(CONTAINER_NAME)

# View logs
logs:
	docker logs -f $(CONTAINER_NAME)

# Access shell in the container
shell:
	docker exec -it $(CONTAINER_NAME) /bin/sh

# Rebuild and restart
rebuild: stop remove build run

# Clean all (stop, remove, rebuild)
restart: stop remove run

# Run tests
test:
	pytest tests/

clean-cache:
	docker builder prune -f