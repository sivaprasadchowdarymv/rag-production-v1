# Architecture — RAG Ultimate 2.0

## System overview

```mermaid
flowchart LR
    subgraph Clients
        UI["Streamlit UI<br/>app.py · ui/"]
        API["REST API<br/>api/main.py (FastAPI)"]
    end
    UI --> SVC
    API --> SVC
    SVC["core/service.RAGService<br/>single server-side entry point"]
    SVC --> AUTH["security/auth<br/>users · roles · tenants · tokens"]
    SVC --> POLI["security/policy_engine<br/>input: injection · harmful · topic · PII"]
    SVC --> WF["agents/workflow<br/>understand → retrieve/summarise → reason → verify → quality"]
    WF --> RET["retrieval<br/>rewriter · multi-query · dense+BM25+fuzzy · RRF · rerank<br/>filters · parent-child · compression"]
    WF --> ROUTER["llm/model_router<br/>mode · sensitivity · context · health · cost"]
    ROUTER --> OLL["Ollama (local)"]
    ROUTER --> CLOUD["Groq · OpenRouter · OpenAI · Anthropic · Bedrock"]
    SVC --> POLO["security/policy_engine<br/>output: sources · grounding · secrets · prompt leak · PII"]
    ING["ingestion<br/>validate → load → OCR → chunk → embed<br/>jobs · retries · versions"] --> VS[("vector store<br/>NumPy per document")]
    ING --> OBJ[("objects<br/>local / S3 · MinIO")]
    SVC --> DB[("database<br/>SQLite / PostgreSQL")]
    ING --> DB
    SVC --> MON["monitoring<br/>JSON logs · request IDs · spans/OTel · Prometheus"]
```

## Request lifecycle

```mermaid
sequenceDiagram
    participant C as UI / API client
    participant S as RAGService
    participant P as PolicyEngine
    participant W as AgentWorkflow
    participant R as ModelRouter
    C->>S: AskRequest(question, documents) + Principal
    S->>S: request id, tenant overrides, rate limit
    S->>P: check_input (injection, harmful, topic, PII)
    alt blocked
        P-->>C: blocked / out_of_scope (audited)
    end
    S->>S: authorized_indexes (tenant + document ACL, current versions only)
    S->>W: run
    W->>W: Query Understanding (task type, variants)
    W->>W: Retrieval (or Summarization) Agent — local, 0 tokens
    W->>R: Reasoning Agent (sensitivity-aware model choice, retries, fallback)
    W->>W: Citation Verification (≤1 regeneration) → Answer Quality (accept/warn/abstain)
    S->>P: check_output (unauthorised sources, grounding, secrets, prompt leak, PII)
    S-->>C: QueryResult (answer, sources, verification, routing, agent trace, security)
```

## Module map (target layout → implementation)

| Target (master prompt) | Implemented in | Notes |
|---|---|---|
| `app.py`, `frontend/` | `app.py`, `ui/pages.py`, `ui/admin_pages.py`, `ui/widgets.py`, `ui/styles.py` | 14 pages in 3 sections |
| `api/routes, middleware, schemas` | `api/main.py`, `api/schemas.py` | request-id middleware, token auth |
| `config/settings.py`, `logging_config.py` | `config/` | every value from env / `.env` / Streamlit secrets |
| `core/orchestrator, pipeline, model_router, session_manager` | `core/service.py`, `core/documents.py`, `core/model_config.py`, `agents/workflow.py`, `llm/model_router.py`, `ui/state.py` | no duplicate orchestrators |
| `ingestion/loaders, parser, ocr, chunker, metadata, processor` | `ingestion/*`, `rag/pdf_parser.py`, `rag/metadata.py` | PDF keeps its specialised parser |
| `retrieval/embeddings, vector_store, bm25, hybrid_search, reranker, query_rewriter` | `rag/embeddings.py`, `storage/vector_store.py`, `retrieval/*` | |
| `generation/llm_factory, prompt_manager, answer_generator, citation_manager` | `llm/providers.py` + `llm/adapters.py` (factory: `make_provider`), `rag/prompts.py`, `agents/master.py`, `agents/master.EvidenceRegistry` + `agents/verifier.canonicalize` | |
| `agents/*` | `agents/orchestrator.py`, `specialists.py`, `retrieval_stage.py`, `master.py`, `verifier.py`, `workflow.py` | |
| `security/*` | `security/*` | |
| `evaluation/*` | `evaluation/*` (+ 1.x `metrics/`) | |
| `database/models, repository, migrations` | `database/*` | |
| `monitoring/*` | `monitoring/*` (+ `ops/telemetry.py`) | |
| `deployment/`, `Dockerfile`, `docker-compose.yml` | same | profiles local / hybrid / production / monitoring |

## Key design decisions

| Decision | Choice | Reason |
|---|---|---|
| Vector store | NumPy matrix per document, keyed by content hash | hybrid scoring touches every node anyway; datasheet-scale corpora; no extra service; pgvector unavailable to test here |
| Database | SQLAlchemy + own versioned migrator | one code path for SQLite and PostgreSQL, migrations are plain Python |
| LLM access | httpx adapters (boto3 only for Bedrock) | explicit, testable wire formats; no SDK lock-in |
| Agents | fixed deterministic sequence, rule-based routing | predictable, cheap, loops impossible; LLM only where it adds value |
| Sensitive data | local-only by default | `ALLOW_SENSITIVE_CLOUD` + `CLOUD_PROVIDERS_ALLOWED` must be set explicitly |
| Streaming | verified answer is streamed to the UI after verification | never show tokens that the verifier or output guard may still reject |
| Background jobs | thread pool + DB job table | no broker for small installs; jobs survive as records |

---

# Answer pipeline details (1.x core, preserved)


## The routing rule

**Text → Groq. Images → Qwen / Gemma (OpenRouter). Search → local.**

| Role | Chain (`provider:model`, tried in order; `llm/catalog.py`) | When it runs |
|---|---|---|
| master | `groq:openai/gpt-oss-120b` → `groq:llama-3.3-70b-versatile` → `openrouter:google/gemma-4-31b-it:free` | every text question |
| vision | free: `gemma-4-31b-it:free` → `gemma-4-26b-a4b-it:free` → `qwen3.8-27b`; quality: `qwen3.8-flash` → `gemma-4-31b-it` → `gemma-4-31b-it:free` | figure questions (images attached), OCR of scanned pages |
| fast | `groq:openai/gpt-oss-20b` → `groq:llama-3.1-8b-instant` | abbreviation resolution (off by default) |
| verifier | `groq:llama-3.3-70b-versatile` → `groq:openai/gpt-oss-20b` | optional LLM check (off by default) |
| embeddings / reranker | local fastembed (nomic, MiniLM cross-encoder); OpenRouter Qwen3 optional | every question, 0 tokens |

A question goes to the vision chain only if **all** hold: the rule-based orchestrator found a figure intent
(figure, graph, plot, curve, chart, diagram, waveform, schematic, image, picture), retrieval kept a figure
with an image file (a figure question always keeps its best figure), `IMAGE_ANSWERS=true`, and an OpenRouter
key is set. The top `MAX_ANSWER_IMAGES` figures are downscaled to `IMAGE_MAX_PX` and attached; the call is a
single call without tools. If every vision model fails, Groq answers from captions and nearby text.

Fallback (`llm/model_router.py`) moves along a chain only for recoverable errors (429/413 rate or token limits,
402 no credits, 404 model gone, 5xx, timeout, empty answer). Entries whose provider has no key are skipped.
Groq requests carry only Groq parameters (`max_completion_tokens`, `reasoning_effort`, `include_reasoning:false`);
OpenRouter requests carry its routing and reasoning objects.

## Request flow

```text
question
  │ agents/orchestrator.py       regex intents -> which specialists run, follow-up rewrite, tools yes/no
  ▼
agents/retrieval_stage.py        text · table · equation · figure · document specialists (local)
  │   hybrid (embeddings + fuzzy + bonuses) + BM25 -> concept links -> local reranker -> fusion (≈1,250 tokens)
  ▼
agents/rag_pro.py                route: figure question + figure evidence -> vision chain with images
  │                                     otherwise                         -> master chain (Groq)
agents/master.py                 [REF-n: TYPE pX] labels; ReAct tools only for calculations / comparisons
  ▼
agents/verifier.py               numbers vs the source each sentence cites, mis-citations, equation symbols,
  │                              local cross-encoder support; image-read values accepted but capped at "partial";
  │                              one bounded correction; optional LLM check (skipped for image answers)
  ▼
metrics/rag_metrics.py           metrics, health score, stage latency, tokens, cost
```

## Indexing flow

```text
PDF ─ rag/pdf_parser.py ─┬─ text      rag/chunking.py
                         ├─ tables    rag/table_extractor.py   (clip-based cell text: robust on PyMuPDF 2.x)
                         ├─ equations rag/equation_extractor.py
                         └─ figures   rag/figure_extractor.py  (image files + caption + nearby text)
    rag/vision.py        scanned pages -> render -> vision OCR -> chunked like normal text (once per document)
                         (VISION_INDEX=true: also describe every figure in advance)
    rag/embeddings.py    local fastembed (default) or Qwen3-Embedding on OpenRouter
```

## Token budget per question (defaults)

| Part | Tokens |
|---|---|
| System prompt + answer format | ~450 |
| Evidence (`MAX_CONTEXT_CHARS=5000`) | ≤ ~1,250 |
| Memory (2 turns) | ≤ ~300 |
| Answer (`MAX_OUTPUT_TOKENS=1500`, incl. low hidden reasoning) | typically 300–700 |
| Calculation questions | + one tool round (~500) |
| Figure questions | + images (≤ 2 × 1024 px) on the vision model instead of Groq |

## Design decisions

* Rule-based router, local retrieval, deterministic verifier: the only LLM call in most questions is the answer.
* Images are seen on demand, not described in advance: no vision tokens for figures nobody asks about.
* Image-read values cannot be checked against text, so they are never shown as fully "verified".
* No vendor SDK: both APIs are OpenAI-compatible; httpx keeps provider-specific parameters explicit.
* NumPy vector store: a datasheet has thousands of nodes, not millions.

## Production guards

Prompt-injection guard (`ops/guard.py`), per-session and per-server rate limits (sized for Groq's free tier),
verified-answer cache, optional `DAILY_BUDGET_USD` for paid OpenRouter use, telemetry without question text,
optional `APP_PASSWORD`, private workspaces via a random key in the link.

## Storage (`DATA_DIR`, default `./data`)

```text
data/documents/<doc_id>/   meta.json, figures/
data/cache/<doc_id>/       nodes + embeddings, vision.json
data/users/<ws>/           chats, feedback, preferences, document list (private per visitor)
data/telemetry/            requests.jsonl
data/models/               local embedding + reranker models
```

Uploaded PDFs are not kept after indexing. `HF_TOKEN` + `HF_DATASET_REPO` sync everything to a private
Hugging Face dataset (`storage/remote.py`).

## Module map

| Package | Purpose |
|---|---|
| `config/` | Settings from env / `.env` / Streamlit secrets |
| `llm/` | `catalog.py` (chains, profiles), `providers.py` (Groq, OpenRouter), `model_router.py` |
| `rag/` | Parsing, chunking, tables, equations, figures, vision OCR, embeddings, retrieval, prompts, tools |
| `retrieval/` | BM25, reranker, evidence fusion |
| `agents/` | Orchestrator, specialists, retrieval stage, master, verifier, pipeline |
| `concepts/`, `chat/`, `learning/` | Concept links; conversations; feedback, preferences, DPO export |
| `metrics/`, `ops/`, `storage/` | Metrics, benchmark, validation; guards, cache, telemetry; workspaces, HF sync |
| `ui/` | Streamlit pages |
| `scripts/check_setup.py` | Live check of keys, models and roles |
| `tests/` | 96 offline tests (fake Groq + OpenRouter server) |
