.PHONY: setup install data demo-start demo-stop demo-eval demo-optimize demo-recommend demo-ab-status demo-deploy cognito-deploy cognito-env cognito-outputs eval-role-setup clean

# === Setup ===
setup: install data
	@echo "Setup complete. Run 'make demo-start' to start the demo."

install:
	pip install -r requirements.txt
	cd frontend && npm install

data:
	@echo "Place Olist CSV files in _data/ then run: python data/migrate.py"

data-migrate:
	python data/migrate.py

data-verify:
	python data/migrate.py --verify

# === Demo ===
demo-start: demo-stop
	@echo "Starting AgentOps Demo (ADOT observability)..."
	@echo "  Agent:    http://localhost:8080"
	@echo "  API:      http://localhost:8000 (ADOT auto-instrumented)"
	@echo "  Frontend: http://localhost:3000"
	@echo ""
	cd frontend && npm run dev &
	OTEL_SERVICE_NAME=agentops-api \
	OTEL_PYTHON_DISTRO=aws_distro \
	OTEL_PYTHON_CONFIGURATOR=aws_configurator \
	OTEL_EXPORTER_OTLP_PROTOCOL=http/protobuf \
	OTEL_RESOURCE_ATTRIBUTES=service.name=agentops-api \
	OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT=true \
	python -m uvicorn api.server:app --host 0.0.0.0 --port 8000 --reload &
	@echo "Demo started. Traces → CloudWatch GenAI Observability."

demo-start-prod: demo-stop
	@echo "Starting production demo..."
	cd frontend && npm run build && npm run preview -- --port 3000 &
	python -m uvicorn api.server:app --host 0.0.0.0 --port 8000 &
	@echo "Production demo started."

demo-stop:
	-pkill -f "uvicorn api.server" 2>/dev/null || true
	-pkill -f "vite" 2>/dev/null || true
	@echo "Demo processes stopped."

# === Evaluation ===
demo-eval:
	@echo "Running evaluation with current prompt version..."
	python evaluation/run_eval.py --limit 5

demo-eval-full:
	python evaluation/run_eval.py

demo-recommend:
	@echo "Generating recommendation via AgentCore Optimization..."
	curl -s -X POST http://localhost:8000/optimization/recommendations \
		-H "Content-Type: application/json" \
		-d '{"evaluator_id": "Builtin.GoalSuccessRate", "lookback_days": 7}' | python -m json.tool

demo-ab-status:
	@echo "A/B test status..."
	curl -s http://localhost:8000/optimization/ab-tests | python -m json.tool

demo-deploy:
	@echo "Optimization status..."
	curl -s http://localhost:8000/optimization/status | python -m json.tool

demo-optimize:
	@echo "Full optimization loop: recommend → evaluate..."
	$(MAKE) demo-recommend
	@echo ""
	@echo "Check Optimization tab in dashboard for progress."
	@echo "Use 'make demo-ab-status' to monitor A/B test results."

demo-compare:
	python evaluation/run_eval.py --compare --limit 5

demo-reset:
	@echo "Resetting optimization pipeline..."
	curl -s -X POST http://localhost:8000/optimization/reset \
		-H "Content-Type: application/json" | python -m json.tool

# === Gateway ===
gateway-setup:
	python agent/setup_gateway.py

gateway-dry-run:
	python agent/setup_gateway.py --dry-run

# === Development ===
frontend-dev:
	cd frontend && npm run dev

frontend-build:
	cd frontend && npm run build

api-dev:
	OTEL_SERVICE_NAME=agentops-api \
	OTEL_PYTHON_DISTRO=aws_distro \
	OTEL_PYTHON_CONFIGURATOR=aws_configurator \
	OTEL_EXPORTER_OTLP_PROTOCOL=http/protobuf \
	OTEL_RESOURCE_ATTRIBUTES=service.name=agentops-api \
	OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT=true \
	opentelemetry-instrument uvicorn api.server:app --host 0.0.0.0 --port 8000 --reload

agent-invoke:
	agentcore invoke '{"prompt": "What was total revenue in 2017?", "prompt_version": "v1"}'

agent-deploy:
	bash infra/deploy-agent.sh

agent-status:
	agentcore status

# === Observability Infra ===
dashboard-setup:
	python infra/dashboard.py

anomaly-setup:
	python infra/anomaly_setup.py

observability-setup: dashboard-setup anomaly-setup
	@echo "CloudWatch dashboard + anomaly alarms configured."

# === Evaluation Infra ===
eval-role-setup:
	bash infra/setup_eval_role.sh

# === Cognito Auth ===
cognito-deploy:
	bash infra/deploy.sh cognito

cognito-env:
	bash infra/deploy.sh cognito-env

cognito-outputs:
	bash infra/deploy.sh cognito-outputs

# === Clean ===
clean:
	rm -rf data/raw/
	rm -rf evaluation/results/
	rm -rf frontend/dist/
	rm -f gateway_config.json
	@echo "Cleaned."
