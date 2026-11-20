# Everlume Solutions Document Intelligence

A local document search application using FastAPI, persistent ChromaDB, SQLite metadata, Ollama embeddings, and Ollama-assisted evidence selection. The frontend uses plain browser JavaScript and CSS; no Node build is required. This is a new standalone application, as requested after the original integration brief. No existing application was modified.

## Windows setup

Use Python 3.11 or 3.12 and install [Ollama](https://ollama.com/download/windows). From this directory in PowerShell:

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
ollama pull nomic-embed-text
ollama pull qwen2.5:3b
.\start.ps1
```

Open http://127.0.0.1:8000. The backend establishes a local session automatically; there is no access-token field. Session credentials use an HttpOnly, SameSite=Strict cookie and are never returned to JavaScript or stored in browser local storage. The API documentation is at http://127.0.0.1:8000/docs.

The launcher binds to loopback. Model downloads and Python installation need internet access once; document processing and inference run locally afterward. Documents are not sent to paid APIs. Chroma's optional product telemetry is disabled by this application.

## Usage

### Any-skill and related-profile matching

The default **Skills → Match any skill** includes a resume when at least one requested skill is supported, including lists joined by AND, OR, commas, or simple whitespace skill lists. Meaningful phrases and roles such as `AI Engineer` and `Machine Learning` stay together, so a civil engineer does not qualify solely through `Engineer`. More complete matches rank above partial matches. Choose **Match all skills** to restore strict combined requirements. API search/ask bodies and recommendation query parameters accept `skill_match: any|all`, defaulting to `any`.

In Any mode, Hybrid and Semantic search can also include supported nearby experience—for example React near Angular, LangGraph near Agentic AI, or paid media near PPC. Related profiles need both content evidence from an approved concept relationship and sufficient calibrated embedding similarity; sharing a dataset name or a character sequence is not sufficient. Exact keywords mode does not add nearby profiles. Unknown relationships remain conservative. Related profiles are labelled, show source evidence, and list requested skills that were not verified. Numeric filters, exclusions, document ownership, dataset selection, deduplication and requested result counts still apply.

### Dataset-specific search

The Discover page includes a **Dataset** dropdown. Search, sourced answers, recommendations, and autocomplete use only that dataset. Dataset names reuse document categories: General, Digital Marketing, .NET, Angular, and any custom categories you create. The browser defaults to General. Empty datasets return an empty result with an explanation and never fall back to other datasets. Changing the selection clears old recommendations and answers and invalidates earlier in-flight responses.

To add a domain folder, open Upload center and choose **Choose folder**, selecting that domain's folder itself (for example `.NET`, rather than its parent containing several domains). Its folder name becomes the dataset for that upload batch. Supported files in its subfolders are included, with a maximum of 200 per batch. You can also select files normally and enter **Dataset / category** manually. This uploads copies; it does not monitor or directly search arbitrary Windows folders. Existing documents can be moved by editing Dataset / category in their preview, without regenerating embeddings.

API clients pass optional `dataset` in the JSON body of search/ask, or as a query parameter for recommendations/suggestions. `GET /api/documents/datasets` returns the authenticated owner's dataset names and document counts. Omitting `dataset` retains the existing all-datasets API behavior. A provided dataset is an exact category name, never a filesystem path. Both SQL candidates and vector retrieval are constrained before validation, deduplication, reranking, count checks, and answer generation. Ownership restrictions still apply.

1. Open **Upload center**, select or drop up to **200 documents**, choose a category and start the upload. Two bounded transfers send files to a persistent backend queue. A single worker indexes one document at a time. Individual progress, failures and retries are shown in the queue. A failed file does not discard successful uploads.
2. Choose keyword, semantic, or hybrid search. Keyword search matches complete, case-insensitive words and whitespace-separated phrases. A multi-word query must match all meaningful keywords; arbitrary substrings and incomplete query fragments do not qualify as keyword results. Semantic search uses Ollama embeddings with model-specific relevance filtering. Hybrid search prioritizes exact phrases, then complete keyword matches, then relevant semantic matches.
3. Open a result to view extracted text at the matching page. PDF page numbers are preserved; DOCX and text formats use one extracted text view because their layouts have no reliable PDF-style page boundaries. Open original downloads the authenticated source file.
4. Generate a sourced answer to let Ollama select evidence. Only exact excerpts verified against retrieved chunks are displayed, with source IDs tied to recommendation cards. Unsupported model paraphrases are discarded. This deliberately favors verifiable, extractive answers over free-form summaries. Document content can still be incorrect; verify the cited source.
5. Replace or delete documents in the preview. Replacements keep the document ID and ownership; failed replacements restore the previous file. Uploads are indexed immediately. A 15-second reconciliation task reindexes changed managed source files and removes deleted ones. Source files live at `data/files/<document-id>`; their display name and type are metadata. Do not add arbitrary files to this directory: additions must use the authenticated upload endpoint so they receive an owner.
6. Use **Document library** to filter by filename or category, browse pages of 25 records, open previews, rename files, update categories, replace sources, or select documents for bulk deletion. Renaming preserves the file extension. Selections can span pages and filters.

The Everlume interface uses a dark navy workspace, orange accents, separate discovery/library/upload views, and the original supplied logo. Each search result includes an evidence-based explanation and a **relevance rating out of 5**. These are deterministic retrieval ratings, not model judgments of a person's suitability or the document's quality, and not probabilities. The API retains numerical similarity/threshold diagnostics; the UI focuses on the matching words, related concepts and source page.

### Large upload behavior

The 200-file flow uses a manifest plus one bounded file request per document; it never sends a single 200-file multipart request. Job status is stored separately from the index, so progress remains readable during inference. Received files continue indexing with the tab closed, provided the backend remains running. Queued work resumes after a server restart, with stable document IDs preventing duplicate documents if a worker was interrupted after committing metadata.

Files that have not reached the server require browser access to the original files: reselect them and use **Resume this batch**. The browser cannot silently reacquire local files after a page refresh. Indexing failures retain their received sources privately in the queue, so **Retry** can work after a page refresh without reuploading. **Cancel remaining** stops pending work and clears retained failed sources; a file already indexing is allowed to finish. Retry or cancel failed batches to manage their temporary disk usage. Batch history shows the 20 most recent batches.

Scanned PDFs need OCR before upload. Encrypted/unreadable PDFs and unsupported encodings may be rejected. Text input is UTF-8. CSV is searched as text, retaining its rows. Markdown, JSON and log files are also supported. This application does not execute document scripts or render document HTML. There is no OCR, legacy `.doc` parser, shared-document ACL editor, or external folder ingestion in this version.

## Authentication and integration

In the default single-user local mode, the browser calls `POST /api/session` using a same-origin application header. The backend requires a loopback client and loopback hostname, rejects foreign origins, and sets an 8-hour HttpOnly session cookie. Cookie-authenticated mutations reject cross-origin requests. Any trusted local user of this Windows workspace can use this local mode; it is not a remote company sign-in system. The backend retains `data/local-token.txt` for compatibility with existing bearer-token API clients, but the frontend never reads or submits it.

For multiple bearer-token API users, set this environment variable **before starting**:

```powershell
$env:DOCUMENT_TOKENS = '{"a-long-random-secret-for-alice":"alice","a-different-random-secret-for-bob":"bob"}'
```

Setting `DOCUMENT_TOKENS` disables automatic browser sessions. An organization identity provider should supply sessions before using a shared remote deployment. Existing bearer-token API clients continue to work. Every document endpoint, upload job, original download, autocomplete, retrieval, metadata update and deletion checks ownership; inaccessible IDs return 404. Do not use usernames as bearer tokens.

For later integration into an existing backend, use `create_app(store=..., tokens=...)` in [backend/main.py](backend/main.py), or adapt its user dependency to the application's verified identity. Never accept an owner ID from request data. Keep the same ownership filtering in [backend/store.py](backend/store.py). The frontend and all APIs are same-origin; CORS is not enabled.

## API

Document routes require either the backend-managed local session or `Authorization: Bearer <token>`.

| Method | Endpoint | Payload / purpose |
|---|---|---|
| POST | `/api/session` | Same-origin loopback browser session bootstrap; no token returned |
| GET | `/api/documents` | Paginated metadata library; `query`, `category`, `page`, `page_size` (up to 50) |
| POST | `/api/documents/upload-jobs` | JSON `filenames` (1–200) and `category`; creates durable upload slots |
| POST | `/api/documents/upload-jobs/{job}/items/{item}` | Multipart `file`; receives and queues a single document |
| POST | `/api/documents/upload-jobs/{job}/items/{item}/retry` | Retry a retained failed source without reuploading |
| GET | `/api/documents/upload-jobs` | Current owner's recent upload batches |
| GET | `/api/documents/upload-jobs/{job}` | Per-file progress, counts, errors and retry availability |
| POST | `/api/documents/upload-jobs/{job}/cancel` | Cancel remaining work and remove retained failed sources |
| POST | `/api/documents/bulk-delete` | JSON `ids` (up to 200); per-document deletion outcomes |
| POST | `/api/documents/upload` | Multipart `file`, optional `category`, `source`; returns indexed ID |
| POST | `/api/documents/upload/batch` | Multipart repeated `files` (1–20), optional `category`, `source`; per-file outcomes |
| POST | `/api/documents/search` | JSON `query`, `mode` (`keyword`, `semantic`, `hybrid`), `limit` |
| POST | `/api/documents/ask` | Same JSON; verified excerpts, source references and follow-ups |
| GET | `/api/documents/recommendations?query=...` | Ranked hybrid recommendations |
| GET | `/api/documents/suggestions?query=...` | Owner-scoped filename autocomplete |
| GET | `/api/documents/{id}` | Metadata and extracted pages |
| PUT | `/api/documents/{id}` | Multipart `file`; replace and reindex while retaining document ID and ownership |
| PATCH | `/api/documents/{id}` | JSON `name`, `category`; update owner-authorized metadata |
| GET | `/api/documents/{id}/file` | Authenticated original file download |
| DELETE | `/api/documents/{id}` | Delete source, metadata and vector chunks |
| GET | `/api/health` | Configuration and API readiness (does not imply models are loaded) |

Scores are retrieval ranking values, **not calibrated confidence percentages**. Each document is represented by its highest scoring chunk. Related documents are the other retrieved matches; follow-ups are deterministic document-specific query suggestions. Empty retrieval and unsupported model output return `No matching information was found.` Ollama failures return 503, rather than silently pretending semantic retrieval worked. Keyword-only search continues to work without Ollama after documents have been indexed.

## Configuration and 16 GB resource budget

Set PowerShell environment variables before startup; `.env` files are not automatically loaded.

| Variable | Default | Purpose |
|---|---|---|
| `OLLAMA_URL` | `http://127.0.0.1:11434` | Local Ollama base URL |
| `CHAT_MODEL` | `qwen2.5:3b` | Answer evidence selector |
| `EMBED_MODEL` | `nomic-embed-text` | Embeddings; model-specific Chroma collection |
| `DOCUMENT_PREFIX` / `QUERY_PREFIX` | Nomic search prefixes | Empty by default for other embedding models |
| `CONTEXT_SIZE` | `4096` | Generation context |
| `RETRIEVAL_LIMIT` | `3` | Default top documents, clamped 1–12 |
| `SEMANTIC_THRESHOLD` | model-specific calibration, or `0.55` fallback | Explicit override of all semantic thresholds |
| `RELEVANCE_CALIBRATION` | `backend/relevance-calibration.json` | Model/prefix/query-version-specific relevance profile |
| `MAX_UPLOAD_MB` | `20` | Per-file upload limit |
| `MAX_CHUNKS` | `2000` | Maximum chunks per document |
| `DOCUMENT_DATA` | `data` | Private persistence directory |
| `DOCUMENT_TOKENS` | generated local token | Token-to-owner JSON map |

Inference is serialized, embedding batches contain eight chunks, and models unload after each call (`keep_alive: 0`) to reduce simultaneous memory use. This trades warm-start speed for memory headroom. Chunks are 1,200 characters with 200-character overlap. Retrieval uses up to 3,000 owner-scoped vector chunks, plus document-level lexical and requirement checks across the owner library. Use one Uvicorn worker: the application coordinates metadata/vector operations with an in-process lock. Multiple workers/processes against the same data directory are not supported. SQLite and Chroma persist separately: versioned vector writes and authoritative metadata prevent incomplete writes from exposing unsupported content; orphan vector cleanup after a process crash may still be needed.

When changing the embedding model, the watcher rebuilds a new model-specific collection. Old collections remain on disk for rollback. The initial implementation scans owner metadata for lexical matching, so it targets local libraries rather than millions of documents. Recalibrate relevance when changing models, prefixes, model weights, or document domains; ranking tests are not a claim of universal semantic accuracy.

## Matching and relevance

`AI` matches the standalone term, including `(AI)` and `ai`, and never the character sequence inside `Emails`, `Maintenance`, or `Familiar`. `ML` does not match `HTML`. `eligib` no longer matches `eligibility`: exact keyword search deliberately requires complete words. Phrases tolerate whitespace and line breaks. Search qualifications and rating evidence come from document content; filenames alone cannot establish a required skill or role. All meaningful query terms can appear in separate positions for a complete keyword match.

Literal matching is implemented once in [backend/keyword_matcher.py](backend/keyword_matcher.py) and used by the existing search service. The frontend highlighter uses the same complete-word boundaries, longest phrase first, and safe text nodes. Semantic synonyms are not highlighted as literal matches. Results include `match_type`, `matched_keywords`, and `semantic_similarity`, and cards identify whether the match is literal or semantic. Semantic-only mode always requires sufficient embedding similarity, including for literal matches. Hybrid scoring uses disjoint bands: exact phrase 0.90–1.00, complete keywords 0.75–0.89, semantic relevance up to 0.74. Scores remain ranking indicators, not probabilities.

For technical queries, the embedding request includes explicit related concepts: Agentic AI → autonomous agents/orchestration; ML Engineer → Machine Learning Engineer, model training/deployment and MLOps. These expansions never create literal matches. Recognized technical context in a passage selects a separately calibrated threshold; it never admits a document without sufficient embedding similarity. Generic terms such as `engineer` alone are insufficient for a multi-word keyword match. Keyword retrieval has a deterministic fallback if Ollama query interpretation is unavailable.

Calibrate using a representative labeled corpus for the configured model:

```powershell
.\.venv\Scripts\python.exe -m scripts.calibrate_relevance
# Review relevance-calibration-report.json before deploying the measured profile:
.\.venv\Scripts\python.exe -m scripts.calibrate_relevance --write
```

The script uses only the synthetic documents in [tests/fixtures/relevance-corpus.json](tests/fixtures/relevance-corpus.json), never private uploaded documents. Extend those labels with representative company examples for deployment. It fits precision-first thresholds from negative examples; where a contextual group contains only positives, it uses the minimum positive similarity with a small margin. Extra paraphrase queries are excluded from threshold fitting. The bundled profile applies only to `nomic-embed-text` with the measured prefixes and query expansion version. Other models fall back to `SEMANTIC_THRESHOLD` until recalibrated. An explicit `SEMANTIC_THRESHOLD` environment setting takes precedence over calibration. Small-corpus calibration does not guarantee zero false positives or complete recall on unseen documents.

## Validation

### Appearance

Use the header's **Appearance** selector for Light, Dark, or System. The default follows the OS. The frontend saves explicit selections under `everlume.theme` in localStorage and restores them before rendering. System mode listens for OS changes and refreshes when a suspended tab resumes; selections also synchronize between tabs. If browser storage is blocked, switching still works for the current tab. Theme changes do not reload the page or alter workspace state. Theme behavior and rendering checks are in [tests/theme.browser.js](tests/theme.browser.js).

### Intent and mandatory search conditions

The existing search endpoint now interprets explicit search syntax before retrieval. Examples include `Best 3 ML engineers with 4+ stars`, `Python and React`, `(Python or Java) and React`, `React without Angular`, `5+ years experience`, and `healthcare RCM`. In Match all skills mode, AND binds more tightly than OR; parentheses can override that order. The default Match any skill mode treats requested skills as alternatives. Exclusions apply to every alternative. `preferably Kubernetes` remains optional. Rating and experience numbers are separate from result counts. Incomplete or unsupported condition syntax returns an empty response with a clarification message.

Search and Ask share an Ollama-driven intent plan. The model selects the operation and topical retrieval text; deterministic validation owns explicit conditions, dataset scope, evidence, and ratings. Unanchored model subjects are ignored. Invalid interpretation returns a clear clarification response. Known abbreviations and technical synonyms have explicit evidence rules; an unfamiliar semantic paraphrase that cannot be verified is conservatively omitted. This is not a guarantee of understanding every possible natural-language construction.

Mandatory conditions are checked against full document pages, not filenames or vector distances. Role evidence requires a matching title or relevant engineering work; selling AI products does not establish AI engineering. Experience requires an explicit, nonconflicting experience statement. A `5+ years` statement establishes a lower bound and cannot establish a maximum of five years. Skill-specific experience needs a corresponding explicit statement. Dates alone and ambiguous or approximate totals are unverified rather than guessed. Documents are evidence of claims, not independent verification of a person's employment history.

Results expose `evidence`, `matched_requirements`, `missing_preferred`, and the unrounded `rating.value`; frontend filters never recalculate that value. Rating thresholds run before display rounding. Search responses include `validation.criteria`, rejection summaries, the number of qualifying unique documents, and duplicates removed. `validation.understanding` records the model intent and retrieval topic; `validation.criteria` records enforced conditions.

Identical file hashes and normalized text are collapsed. Near-duplicate profiles require matching identity/contact evidence and substantial text overlap, so similar skill sets alone do not merge candidates. The highest-scoring qualifying version wins; upload time breaks ties. Deduplication occurs before count validation. `Top 5` returns exactly five unique qualifying results or none, regardless of the normal API limit. Without an explicit count, all qualifying unique documents are returned, with `MIN_RECOMMENDATIONS=1` as the minimum. Set that environment variable to raise the minimum; `RERANK_LIMIT=8` bounds documents sent to the language model (maximum 20). Explicit query counts support 1–100.

Use `python -m scripts.validate_intent_search` through the configured virtual environment for an isolated real-Ollama check and a 500-document backend capacity check. It writes `intent-search-validation.json` and never touches the normal document library. The capacity stage uses deterministic embeddings to separate backend latency from model inference. Actual model latency is measured separately; read the report before estimating interactive performance.

```powershell
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m scripts.benchmark
# Optional full retrieval test with real local Ollama embeddings:
$env:RUN_OLLAMA_TESTS = '1'
.\.venv\Scripts\python.exe -m pytest tests/test_relevance_ollama.py -q
```

Tests use real persistent Chroma with deterministic embedding fixtures to isolate API behavior; they do not claim to test a real model. The benchmark uses the actual configured Ollama models, uploads a temporary sample policy, measures index/search/answer times and verifies that answer excerpts match cited evidence. Its result is written to `benchmark-result.json`. It does not add sample documents to your normal library. Repeat it under your normal workload before judging performance; one small policy is a smoke test, not a load test.

[tests/highlighting.browser.js](tests/highlighting.browser.js) contains executable assertions for the production highlighter. Run its contents in the app's browser context (for example, the browser developer console). See [VALIDATION.md](VALIDATION.md) for measured results.

[tests/workspace.browser.js](tests/workspace.browser.js) adds browser assertions for automatic sessions, private credentials, reasons/ratings, 200-file selection and page navigation. [tests/test_workspace.py](tests/test_workspace.py) exercises the complete 200-file upload/index/list/delete lifecycle with real API and Chroma operations and deterministic embeddings. This is a capacity/correctness test, not a claim about 200 real documents' Ollama processing time.

Implementation follows the [Ollama embeddings API](https://docs.ollama.com/api/embed), [Ollama structured output API](https://docs.ollama.com/capabilities/structured-outputs), [Nomic task prefixes](https://huggingface.co/nomic-ai/nomic-embed-text-v1.5), and [Chroma explicit embedding storage API](https://docs.trychroma.com/docs/collections/add-data). Citation selection is constrained to exact excerpts from retrieved text; generated claims are then independently checked for support before display.

### Unified query understanding and answers

Both Search and Ask use the same local Ollama query-understanding pipeline. The selected dataset supplies context automatically. The model interprets generic questions, document counts/lists, comparisons, skill filters, and recommendations by meaning rather than a list of supported phrases. Quoted subjects must occur in the original query; known explicit skills, Boolean conditions, rating/experience limits, exclusions, and counts remain backend-enforced. No model-selected dataset can override the dropdown.

Metadata questions use owner-scoped indexed-file counts and verified document identities. Skill searches use existing hybrid retrieval and full-document validation. Other questions retrieve relevant evidence and generate concise natural-language claims. Citation quotes are constrained to exact source excerpts, independently checked for entailment, and rejected for unsupported quantities or evaluation scales. These checks reduce hallucinations; a small local model remains fallible. Missing evidence or criteria produces an explanation or clarification instead of a fabricated conclusion.

Understanding plans are cached for 128 query/dataset combinations. Query embeddings are cached separately; document results and permissions are always refreshed. `CHAT_KEEP_ALIVE=5m` and `EMBED_KEEP_ALIVE=5m` keep lightweight models warm; set either to `0` to release them immediately. Full answers include interpretation, composition, and verification, so they take longer than a keyword lookup. `SEARCH_AI_ENRICHMENT` controls the older adapter's optional tie-breaking and is not required by the unified pipeline.

All qualifying unique document matches remain available through result pagination. Answers use a bounded evidence subset; the UI identifies partial citation coverage. General answers use only the selected uploaded documents, not unrestricted world knowledge.

Run the optional real-model smoke test with `.\.venv\Scripts\python.exe -u -m scripts.validate_unified_assistant`. It creates an isolated synthetic library and does not modify uploaded user files. Existing model adapters without structured understanding retain the compatibility API path.
## General AI and document AI

The interface now offers Auto, General AI, Document AI, and Hybrid AI. General questions use local Ollama without accessing document retrieval. Document queries retain the existing evidence validation. Hybrid answers explicitly separate document findings from general model guidance. Recent, bounded conversation context supports follow-ups and clears when the dataset changes.

Both existing POST search/ask endpoints accept `query_mode` and optional bounded `history`; the API default remains `document` for compatibility, while the UI defaults to `auto`. General AI is pretrained model knowledge, not verified document evidence or live web information. Test local model routing with `.venv/Scripts/python.exe -m scripts.validate_ai_routing`.

