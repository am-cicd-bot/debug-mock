.PHONY: dev traffic docker-up docker-down k8s-apply k8s-delete test

dev:
	bash ./scripts/run_local.sh

traffic:
	python3 ./scripts/simulate_traffic.py --requests 6 --concurrency 3

docker-up:
	docker compose up --build

docker-down:
	docker compose down -v

k8s-apply:
	kubectl apply -f k8s/namespace.yaml
	kubectl apply -f k8s/configmap.yaml
	kubectl apply -f k8s/secrets.yaml
	kubectl apply -f k8s/observability.yaml
	kubectl apply -f k8s/core-ledger.yaml
	kubectl apply -f k8s/dispute-agent.yaml
	kubectl apply -f k8s/ingress.yaml

k8s-delete:
	kubectl delete namespace meridian-disputes

test:
	python3 -m unittest discover -s tests
