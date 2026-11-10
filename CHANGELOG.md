# Changelog

## 2.0.5 — 2026-11-10

### Added
- **🎓 Guide & Test Lab** page: setup check with fixes, upload and question pipelines explained step by step,
  one-click Test Lab (sample documents with known answers; 6 answer tests and 5 safety tests run through the real
  RAGService and are auto-checked: ✅ pass · ❌ fail · ➖ not tested, never a pass that was not checked), checklist.
- **ℹ️ What is this page?** help on every page (what, how to use, what to try, expected result).
- **🧑‍🏫 How this answer was made**: plain-English explanation under every answer, built from the real security
  decisions, agent trace, retrieval, routing and verification. *Beginner help* toggle in the sidebar.
- Chat onboarding: load the sample documents or open the guide when no documents exist.

## 2.0.0 — 2026-11-10

Production platform release. All 1.x functionality preserved (96 original tests still pass unchanged in
behaviour); 172 new tests.

### Added
- **Ingestion**: DOCX, PPTX, XLSX, CSV, TXT, Markdown, HTML, JSON, PNG/JPG (tesseract OCR) besides PDF; local OCR
  of scanned PDF pages; magic-byte validation, macro/encryption/zip-bomb/executable rejection; chunk strategies
  recursive · fixed · semantic · structure; document versioning, de-duplication, deletion without stale vectors;
  background ingestion with retries and failed-job tracking; originals in local or S3/MinIO storage.
- **Retrieval**: query rewriting, abbreviation/synonym expansion, multi-query RRF, metadata pre-filters,
  parent-child (small-to-big), context compression, `HybridSearcher` with every score exposed, debugger page.
- **Models**: Ollama (chat, tools, vision, embeddings), OpenAI-compatible, Anthropic, AWS Bedrock; local/cloud/
  hybrid modes; manual model; sensitivity-aware routing (confidential → local only); context-window checks;
  cost/latency strategies; retries with backoff + Retry-After; circuit breaker; token and cost tracking.
- **Agents**: controlled workflow — query understanding, retrieval or summarisation, reasoning, citation
  verification, answer quality (accept/warn/abstain); timeouts, fallbacks, execution trace.
- **Security**: injection (direct, indirect, obfuscated), PII (11 types), harmful content, topic restrictions,
  grounding guard, output guard (secrets, prompt leakage, PII), tenant policies; accounts, RBAC, tenants, API
  tokens, lockout, audit log.
- **API**: FastAPI with token auth, documents, query, retrieval debug, jobs, audit, `/healthz` `/readyz` `/metrics`.
- **Data**: SQLAlchemy schema (SQLite / PostgreSQL), versioned migrations, DB conversations, backup/verify/restore.
- **Evaluation**: controlled corpus + 18-question dataset, retrieval/generation/operational metrics,
  baseline-vs-upgraded runner, stored runs, JSON/CSV/Markdown export, optional RAGAS adapter.
- **Observability**: JSON logs with request ids and redaction, spans + OpenTelemetry, Prometheus metrics,
  Grafana dashboard, usage analytics.
- **UI**: Dashboard, Ingestion, Retrieval debugger, Agent traces, Evaluation, Models, Security, Users & roles,
  Audit log; model/mode selectors; streamed verified answers; routing explanation.
- **Deployment**: lock file, multi-stage non-root Dockerfile, compose profiles local/hybrid/production/monitoring,
  Caddy HTTPS, GitHub Actions CI (lint, bandit, tests with PostgreSQL, pip-audit, image build + Trivy) and release.

### Fixed
- Offline mode: local model loads no longer stall questions (~40 s per call before; first question 119.5 s →
  0.32 s); failed downloads are not retried for MODEL_RETRY_S.
- Answer relevance compared vectors from two different embedding models when remote/Ollama embeddings were used.
- Heading-only page text produced no chunk; uploads were always renamed to `.pdf`.
- See `docs/FINAL_TEST_REPORT.md` for the full defect list.

### Security
- Pillow ≥ 13.0 (39 advisories in 12.x); invisible/bidi characters removed from source; metrics not public.

### Known limitations
- pgvector not used (NumPy vector store); live Ollama/cloud providers and container builds not verified in the
  build environment — see the test report.
