# RAG∞ Ultimate 2.0

Secure, multi-LLM Retrieval-Augmented Generation platform: verified, cited answers from your documents,
running **fully offline** (Ollama + local embeddings) or with **optional cloud models** (Groq, OpenAI,
Anthropic, AWS Bedrock, OpenRouter), behind authentication, tenant isolation and layered guardrails.

```text
Streamlit UI ─┐                          ┌─ ingestion: PDF DOCX PPTX XLSX CSV TXT MD HTML JSON PNG/JPG (+OCR)
REST API ─────┴─▶ RAGService ─ policy ─ agents ─ retrieval (rewrite · multi-query · dense+BM25+fuzzy · RRF · rerank)
                     │            │        └─ model router (local/cloud/hybrid · sensitivity · cost · fallback)
                     └─ SQLite/PostgreSQL · object storage · Prometheus/OTel · audit log
```

See [ARCHITECTURE.md](ARCHITECTURE.md) for diagrams and design decisions.

## Quick start (local)

```bash
python -m venv .venv && . .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.lock                     # pinned, audited dependencies
sudo apt-get install -y tesseract-ocr                # OCR (macOS: brew install tesseract)
cp .env.example .env                                 # edit: pick a model option below
streamlit run app.py                                 # http://localhost:8501
```

Model options in `.env` (any combination):

```bash
# offline / local
OLLAMA_BASE_URL=http://localhost:11434
OLLAMA_MODEL=llama3.1:8b          # ollama pull llama3.1:8b
LLM_MODE=local                    # never call a cloud API
# free cloud text model
GROQ_API_KEY=gsk_...
# other providers
OPENAI_API_KEY=...   ANTHROPIC_API_KEY=...   BEDROCK_REGION=us-east-1   OPENROUTER_API_KEY=...
```

Without any model the app still works: it shows the best matching evidence.

## Production (accounts, PostgreSQL, HTTPS)

```bash
# .env: AUTH_MODE=users ADMIN_USERNAME=admin ADMIN_PASSWORD=... POSTGRES_PASSWORD=... MINIO_ROOT_USER=...
#       MINIO_ROOT_PASSWORD=... DOMAIN=rag.example.com
docker compose --profile production up -d                    # app, api, postgres, minio, caddy (HTTPS)
docker compose --profile production --profile monitoring up -d   # + prometheus, grafana
```

Profiles: `local` (offline), `hybrid`, `production`, `monitoring` — [docs/DEPLOYMENT_GUIDE.md](docs/DEPLOYMENT_GUIDE.md).
REST API: `uvicorn api.main:app --port 8000` → `/docs` (OpenAPI), `/healthz`, `/readyz`, `/metrics`.

## Tests and checks

```bash
pip install -r requirements-dev.txt
python -m pytest                                   # 268 tests, offline (fake LLM server + fake embedder)
TEST_DATABASE_URL=postgresql://user:pass@localhost:5432/rag_test python -m pytest   # + PostgreSQL variants
ruff check . && bandit -c pyproject.toml -r . -ll && pip-audit -r requirements.lock
python -m evaluation.benchmark [--generation]      # baseline vs upgraded report → data/evaluations/
python -m scripts.smoke_test --api http://127.0.0.1:8000 --ui http://127.0.0.1:8501 --user admin --password '...'
python -m scripts.backup create|verify|restore
```

## What is where

| | |
|---|---|
| `core/` | RAGService (single server-side entry point), tenant document access, tenant overrides |
| `ingestion/` | validation, loaders, OCR, chunk strategies, processor, background jobs |
| `retrieval/` + `rag/` | query rewriter, hybrid search, BM25, reranker, fusion; parsing, embeddings, prompts |
| `llm/` | providers + adapters (Ollama, OpenAI, Anthropic, Bedrock), catalog, pricing, router |
| `agents/` | orchestrator, specialists, master (reasoning), verifier, workflow |
| `security/` | injection, PII, harmful, topics, grounding, output guard, policy engine, auth/RBAC |
| `database/` | models, repository, migrations |
| `evaluation/` | corpus, dataset, metrics, benchmark, RAGAS adapter |
| `monitoring/` | Prometheus metrics, tracing/OTel, analytics |
| `api/`, `ui/` | FastAPI, Streamlit pages |
| `deployment/` | Prometheus, Grafana, Caddy configs |

## Documentation

[Beginner step-by-step guide (HTML)](docs/BEGINNER_GUIDE.html) · [User guide](docs/USER_GUIDE.md) · [Admin guide](docs/ADMIN_GUIDE.md) · [Deployment](docs/DEPLOYMENT_GUIDE.md) ·
[Security audit](docs/SECURITY_AUDIT.md) · [Final test report](docs/FINAL_TEST_REPORT.md) ·
[Production checklist](docs/PRODUCTION_READINESS_CHECKLIST.md) · [Changelog](CHANGELOG.md) ·
[Execution tracker](PROJECT_EXECUTION_TRACKER.md) · Phase 0 audit: [docs/REPOSITORY_AUDIT.md](docs/REPOSITORY_AUDIT.md)

## Honest status

Verified in the build environment: everything in the test report marked ✅ (268 tests, live UI+API+PostgreSQL
smoke test, backup/restore, audits). **Not verifiable there** (network/credential restrictions): live Ollama and
cloud model calls, real embedding/reranker model quality, `docker build`, Trivy and GitHub Actions runs. These
paths are implemented and tested against protocol-faithful fakes; confirm them on your infrastructure with the
checklist in [docs/PRODUCTION_READINESS_CHECKLIST.md](docs/PRODUCTION_READINESS_CHECKLIST.md).
