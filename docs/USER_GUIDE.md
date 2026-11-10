# User Guide

## Sign in
With accounts enabled you sign in with the username and password your administrator gave you. Otherwise the
app opens directly (single-user mode); bookmark the link, it holds your private workspace.

## Add documents — *Documents*
Drop files on the uploader: **PDF, Word (.docx), PowerPoint (.pptx), Excel (.xlsx), CSV, text, Markdown, HTML,
JSON, PNG/JPG** (images and scanned pages are read with OCR). Choose a **sensitivity**:

| Label | Meaning |
|---|---|
| public / internal | may be answered by any enabled model |
| confidential / restricted | answered only by **local** models unless an administrator allows cloud use |

Documents containing personal data (IDs, account numbers, …) are classified confidential automatically.
Uploading a file with the same name again creates a **new version**; the old version is no longer searched.
Identical files are stored once. Large batches: *Ingestion* → *Background upload*; follow progress there.

## Ask — *Chat*
Type a question. The answer cites its evidence as `[REF-n: TYPE pX]`; open **Evidence** to see each passage
(page, section, table row, figure). A badge shows whether citations were **verified**. Follow-up questions keep
context ("and at 85 °C?"). Use **Copy**, **Regenerate**, and 👍 / 👎 feedback (the assistant adapts its style).

In the sidebar: **Model mode** (hybrid / local / cloud) and **Model** (automatic routing or a specific model).
**Why this model** under an answer explains the routing decision (e.g. "confidential data: local only").

What you may see instead of an answer:

| Message | Why |
|---|---|
| "…attempt to override the assistant's instructions…" | the question looked like a prompt-injection attempt |
| "…outside what this assistant can help with" / out-of-scope | content or topic policy of your organisation |
| "I could not find enough reliable evidence…" | the draft answer was not supported by the documents, so it was withheld |
| "NOT FOUND IN DOCUMENT" | the documents do not contain the answer |
| "Personal data in your question was redacted" | e-mails, IDs etc. are removed before any model sees them |

## Other pages
* **Validate** — generate questions from a document and check answers.
* **Dashboard / Analytics** — usage, latency, cost, feedback.
* **Retrieval debugger** — see how a query is rewritten and every candidate's dense, BM25, fuzzy, fusion and
  rerank scores, with filters by document, element type and page.
* **Agent traces** — the agents that ran for each answer, their timing, routing, verification and security
  decisions.
* **Evaluation** — run the benchmark (baseline vs upgraded) and download reports.

## Tips
Ask specific questions with symbols and units ("max VIN at 25 °C"). For summaries say "Summarize this document".
Use the debugger when an answer misses: it shows whether the right passage was found.
