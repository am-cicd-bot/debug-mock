# Meridian Commercial Bank — DisputeOps Agentic Platform

Autonomous charge dispute intake, policy retrieval, triage, and clearing platform built for commercial banking operations on Kubernetes (GKE).

## Architecture Overview

The platform is composed of two services and a self-contained, vendor-neutral observability stack (no reliance on managed cloud logging, WAF, or proprietary agent runtimes):

1. **`dispute-agent` (`:8080`)** — FastAPI application serving the **DisputeOps Workbench UI**, REST API, TF-IDF policy RAG retriever (`policies/*.md`), and multi-step tool-calling agent orchestrator.
2. **`core-ledger` (`:8081`)** — Deterministic Core Banking & Card Network Clearing service managing commercial accounts, 90-day transaction history, merchant risk profiles, provisional credit ledger postings (`/v1/ledger/provisional-credit`), and card/ACH network filings (`/v1/network/chargeback`).
3. **In-Cluster Open-Source Observability** — Structured JSON `stdout` logs (`kubectl logs`), Prometheus `/metrics` endpoints on both services, OpenTelemetry OTLP trace export to **Jaeger** (`:16686`), plus an in-memory span buffer inspectable directly in the web workbench (`/api/telemetry/spans`).

```
┌───────────────────────────┐        ┌──────────────────────────────────────┐
│ NGINX IngressController   │───────▶│ dispute-agent (:8080)                │
│ (Standard K8s Ingress)    │        │  ├─ DisputeOps Web Portal            │
└───────────────────────────┘        │  ├─ ReAct / Tool-Calling Agent Loop  │
                                     │  └─ Policy Corpus RAG (policies/)    │
                                     └──────────────────┬───────────────────┘
                                                        │ HTTP JSON
                                                        ▼
                                     ┌──────────────────────────────────────┐
                                     │ core-ledger (:8081)                  │
                                     │  ├─ Accounts & Settled Statement DB  │
                                     │  ├─ Provisional Credit Posting API   │
                                     │  └─ Card / NACHA Clearing Engine     │
                                     └──────────────────────────────────────┘
```

## LLM Configuration

`dispute-agent` supports external and self-hosted models via environment variables:

- **Gemini (`LLM_PROVIDER=gemini`)**: Set `GEMINI_API_KEY` (defaults to `gemini-2.5-flash`).
- **OpenAI / Self-Hosted vLLM (`LLM_PROVIDER=openai`)**: Set `LLM_BASE_URL` and `OPENAI_API_KEY`.
- **Offline Deterministic Engine (`LLM_PROVIDER=local` or `auto` without API keys)**: Executes the multi-turn tool-calling workflow locally against live RAG results and downstream `core-ledger` responses so the stack runs end-to-end out of the box.

## Running on GKE (Self-Contained Kubernetes Stack)

All manifests live under `k8s/` and use standard Kubernetes primitives (`Namespace`, `ConfigMap`, `Secret`, `Deployment`, `Service`, `Ingress` with `nginx`, plus in-cluster `Jaeger` and `Prometheus`):

```bash
# Build & push container images to your registry, then deploy:
make k8s-apply

# Inspect pods, stdout JSON logs, and port-forward tools without GCP services:
kubectl -n meridian-disputes get pods
kubectl -n meridian-disputes logs -l app=dispute-agent -f
kubectl -n meridian-disputes port-forward svc/dispute-agent 8080:8080
kubectl -n meridian-disputes port-forward svc/jaeger-collector 16686:16686
kubectl -n meridian-disputes port-forward svc/prometheus 9090:9090
```

## Running Locally

### Option A: Direct Python Processes
```bash
chmod +x scripts/run_local.sh
make dev
```
Open **http://127.0.0.1:8080** in your browser.

### Option B: Docker Compose (with Jaeger & Prometheus)
```bash
make docker-up
```
- **DisputeOps Workbench:** http://localhost:8080
- **Core Ledger OpenAPI:** http://localhost:8081/docs
- **Jaeger Trace UI:** http://localhost:16686
- **Prometheus UI:** http://localhost:9090

## Generating Dispute Traffic

With the stack running, simulate concurrent commercial dispute submissions:

```bash
make traffic
```
