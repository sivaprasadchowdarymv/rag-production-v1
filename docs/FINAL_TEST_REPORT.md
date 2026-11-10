# Final Test Report — RAG Ultimate 2.0.0

Date: 2026-11-10 · Python 3.13.18 · PostgreSQL 16.15 · tesseract 5.3.4 · Streamlit 1.67 · Linux x86-64 (2 vCPU).

## Summary

| Gate | Command | Result |
|---|---|---|
| Unit + integration + security + performance tests | `TEST_DATABASE_URL=postgresql://… python -m pytest` | **268 passed, 0 failed, 0 skipped** (≈ 91 s) — baseline was 96 |
| Lint | `ruff check .` | clean |
| Static security analysis | `bandit -c pyproject.toml -r . -ll` | **0 high, 0 medium** (11 low) |
| Dependency vulnerabilities | `pip-audit -r requirements.lock` | **No known vulnerabilities** |
| Live stack smoke test (real processes) | `python -m scripts.smoke_test …` | **17 / 17 passed** — `docs/evaluation/smoke_test_results.json` |
| Backup → verify → restore (CLI, PostgreSQL) | `python -m scripts.backup create / verify / restore` | passed; 4 documents, 39 chunks, 10 audit events back after restore |
| Retrieval benchmark (real run) | `python -m evaluation.benchmark` | `docs/evaluation/BASELINE_VS_UPGRADED_lexical.md` |
| Compose profiles | `docker compose --profile … config` | local, hybrid, production, monitoring: valid |
| Container image build / Trivy scan | `docker build .` | **BLOCKED** — Docker Hub refused by the sandbox proxy |

Live stack = API (uvicorn) + UI (Streamlit) + PostgreSQL, `AUTH_MODE=users`, JSON logs. The only stand-in was the
LLM provider: the repository's scripted fake server played Groq and Ollama, because no real model endpoint is
reachable from the build sandbox. **Answer quality on real models was therefore not measured here.**

## Validation matrix (master prompt §Phase 12)

Status: ✅ tested successfully · 🟡 partially tested · ⛔ blocked by missing external credentials/infrastructure.

| # | Area | Status | Evidence |
|---|---|---|---|
| 1 | Application startup | ✅ | live: `/healthz`, `/readyz`, `/_stcore/health`; AppTest of `app.py` in both auth modes |
| 2 | Document upload | ✅ | UI uploader (AppTest), REST upload (smoke, `test_api_end_to_end_isolation`) |
| 3 | PDF ingestion | ✅ | `tests/test_ingestion.py`, smoke upload of the datasheet (text, tables, equations, figures) |
| 4 | OCR | ✅ | `test_image_ocr` (real tesseract), smoke PNG upload; scanned PDF pages via `_local_ocr_pdf` + vision OCR tests |
| 5 | Chunking | ✅ | 4 strategies × size bounds, cache-key test, Markdown structure, heading-only fallback |
| 6 | Embeddings | 🟡 | local fastembed path, OpenRouter and **Ollama** embeddings tested with deterministic fakes; the real nomic model could not be downloaded here |
| 7 | Vector indexing | ✅ | NumPy store, cache keys, stale-vector removal on new version / delete |
| 8 | BM25 retrieval | ✅ | real (no model needed): benchmark + `test_every_mode_returns_scored_hits[bm25]` |
| 9 | Hybrid retrieval | ✅ | RRF of dense + BM25 + fuzzy; multi-query variants vote; filters; parent-child |
| 10 | Reranking | 🟡 | code path tested with the offline fake cross-encoder and the OpenRouter reranker fake; real MiniLM not downloadable here |
| 11 | Local LLM responses | 🟡 | Ollama adapter (chat, tools, images, embeddings) against a protocol-faithful fake; **live Ollama ⛔** (registry blocked) |
| 12 | Cloud LLM responses | ⛔ / 🟡 | no credentials; OpenAI + Anthropic wire formats tested against strict fakes, Bedrock with botocore Stubber |
| 13 | Model fallback | ✅ | 429 with Retry-After, 5xx retries, circuit breaker, chain fallback, sensitive-data exclusion |
| 14 | Multi-agent execution | ✅ | `tests/integration/test_agent_workflow.py` (trace, summarisation, timeout, fallbacks, abstention) |
| 15 | Prompt injection | ✅ | 15 direct variants incl. zero-width and base64, indirect injection in a document, 9 benign false-positive checks |
| 16 | PII detection | ✅ | 11 entity types, checksums, policies, input redaction verified at the provider, output masking |
| 17 | Harmful-content controls | ✅ | 6 categories + supportive self-harm response + false-positive cases (one real FP fixed) |
| 18 | Topic restrictions | ✅ | restricted, allowed boundary, tenant overrides, UI policy probe |
| 19 | Grounding | ✅ | grounding guard + verifier + quality agent; unsupported answers abstained or corrected |
| 20 | Citation correctness | ✅ | verifier (invalid / mis-citations), benchmark `citation_correctness` metric |
| 21 | Tenant isolation | ✅ | service + REST API: cross-tenant listing, query, retrieval-debug and delete all denied and audited |
| 22 | Authentication | ✅ | PBKDF2, lockout, password policy, tokens (hashed, revocable), UI login (AppTest), API bearer auth |
| 23 | Database persistence | ✅ | SQLite **and PostgreSQL 16**: repository parity, migrations 0001→0002 on existing data, DB conversations |
| 24 | Conversation history | ✅ | JSON store (1.x tests) + DB store (user-scoped, variants on regenerate) |
| 25 | Error recovery | ✅ | ingestion retries/backoff, failed-job tracking, provider fallback, agent timeouts, fail-fast model loading, evidence-only answers |
| 26 | Performance | ✅ | `tests/performance`: retrieval p50 2.9 ms / p95 3.1 ms over 300 nodes; 16 concurrent API queries p95 0.27 s (fake model); first live question 0.32 s after the model-loading fix (was 119.5 s) |
| 27 | Backup and restoration | ✅ | automated round trips on SQLite + PostgreSQL, tamper detection, CLI cycle on the live stack |

## Defects found and fixed during the transformation

| Phase | Defect | Impact |
|---|---|---|
| 2 | Heading-only text produced no chunk (short OCR results, title slides lost) | data loss in index |
| 2 | Re-entrant lock deadlock in the background ingestion pool | uploads hang |
| 2 | `sanitize_filename` forced every file to `.pdf` | wrong format detection |
| 6 | Violence rule matched "kill a hung process" | false refusals |
| 6 | Superseded versions readable without accounts | stale retrieval |
| 7, 12 | Offline model loads retried a blocked download for ~40 s per call; first question took 119.5 s | unusable offline mode |
| 10 | Agent thread pool dropped request context; service minted a second request id | broken log/trace correlation |
| 11 | Literal bidi/zero-width characters in source; Pillow 12.3 advisories; Caddy exposed `/api/metrics` | security |
| 12 | `answer_relevance` compared vectors from two different embedding models | wrong metric with Ollama/OpenRouter embeddings |

## How to reproduce

```bash
pip install -r requirements-dev.txt
sudo apt-get install -y tesseract-ocr          # OCR tests
export TEST_DATABASE_URL=postgresql://rag:ragtest@127.0.0.1:5432/rag_test   # optional: PostgreSQL variants
python -m pytest                               # full suite
ruff check . && bandit -c pyproject.toml -r . -ll && pip-audit -r requirements.lock
python -m evaluation.benchmark                 # retrieval benchmark (add --generation with a configured model)
python -m scripts.smoke_test --api http://127.0.0.1:8000 --ui http://127.0.0.1:8501 --user admin --password '…'
```

## Not verified here (do this on your infrastructure before go-live)

1. `docker build` + Trivy scan + `docker compose --profile production up` (needs Docker Hub access) — CI does this.
2. Live Ollama with a pulled model; live OpenAI / Anthropic / Bedrock with real keys.
3. Real fastembed models (dense retrieval + cross-encoder): rerun `python -m evaluation.benchmark` and
   `--generation` once models are available; compare with the lexical-only numbers in `docs/evaluation/`.
4. Caddy TLS issuance on a public domain; Grafana dashboard against live Prometheus.
