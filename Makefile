.PHONY: test frontend-test frontend-build docker-build docker-config

test:
	uv run pytest -q

frontend-test:
	npm --prefix frontend run test:run

frontend-build:
	npm --prefix frontend run build

docker-config:
	docker compose config

docker-build:
	docker build --target runtime -t gitresume-api:test .
	docker build -t gitresume-frontend:test frontend
