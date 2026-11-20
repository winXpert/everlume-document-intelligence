# Validation on this Windows machine

## Complete search results — November 19, 2026

The backend suite passed 99 tests, with one optional Ollama corpus test skipped, in 44.59 seconds. New coverage verifies 25 matching documents without default truncation, explicit limits and Top N requests, bounded query-vector caching with fresh additions/deletions, and semantic evidence beyond chunk 3,000. Six browser checks passed for 20-card pagination, total counts, both page directions, last-page boundaries, and clearing pagination on dataset changes. Editor diagnostics reported no errors in changed Python and JavaScript files. Semantic scoring uses exact cosine similarity over owner/dataset-scoped vectors in batches of 512; only query embeddings are cached, capped at 128 entries. AI context remains bounded independently of the number of listed matches.

## Any-skill and nearby profile recommendations — November 18, 2026

The backend suite passed **96 tests**, with one optional full-corpus Ollama test skipped, in 50.79 seconds. Eleven additional tests cover any-one matching for AND/OR/comma/whitespace lists, full-versus-partial ranking, clearly labelled related profiles without exact keywords, evidence plus similarity filtering, literal-only keyword mode, dataset boundaries, experience/rating/exclusion filters, exact result counts, answer source selection, optional strict mode, and substring/irrelevant-role rejection.

All **80 browser assertions** passed (seven new flexible-search assertions plus 73 existing checks). The default selector is Match any skill. Requests carry the selected policy; related cards identify missing exact skills, use truthful related-evidence labels, and do not fabricate keyword highlights.

An isolated actual-Ollama smoke test indexed three synthetic profiles using `nomic-embed-text` and queried `Angular developers` with `qwen2.5:3b` assistance. It returned the Angular profile first (4.870/5), a React profile as Related profile (2.225/5), and excluded an invoices/maintenance profile. Indexing and search together took 23.69 seconds. It did not read or change user documents. Related retrieval is limited to supported concept relationships plus calibrated similarity; it is not a claim that every related career path can be inferred automatically.

## Dataset-restricted search — November 18, 2026

The backend suite passed **85 tests**, with one optional full-corpus Ollama test skipped, in 48.69 seconds. Thirteen dataset tests cover exact category scoping in keyword/semantic/hybrid retrieval, model reranking inputs, answer context, empty datasets without fallback, scoped result counts, autocomplete, recommendations, owner-only dataset listings, metadata reassignment, changes during inference, invalid inputs, and backward-compatible API calls without a dataset. Tests use real SQLite/Chroma and deterministic embedding fixtures; no new real-model throughput claim is made.

All **73 browser assertions** passed: 11 new dataset checks plus the previous 62. They verify selected-dataset request payloads, autocomplete parameters, clearing previous answers/results, ignoring stale in-flight responses, preserving the query and selected dataset, folder-to-dataset assignment, and a nonmutating empty-dataset API request. Synthetic browser fixtures do not change uploaded user documents. Dataset names reuse categories and vector queries are restricted by owner plus IDs selected from the current category metadata, so category edits do not need embedding regeneration.

## Persistent appearance — November 18, 2026

Frontend-only appearance support adds Light, Dark, and System selections without changing backend or AI search code. The browser suite covers 29 theme assertions: before-body resolution, saved light/dark preferences, missing or invalid preferences, simulated system changes, suspended-tab refresh, explicit overrides, blocked storage, cross-tab events, selector state, both theme palettes, native control color schemes, and preservation of queries, filters, selected files and rendered recommendations. The 33 existing browser assertions also passed.

A separate live reload restored Light mode from localStorage. All three workspace views fit both 390-pixel and 1,440-pixel viewports in light and dark modes (12 layout checks). Measured foreground/background token pairs met 4.5:1 text contrast: light secondary text on white 4.76:1, on the secondary surface 4.55:1; light status labels 5.91–6.84:1; dark primary text 18.06:1 and secondary text 6.32:1. System-change handlers are tested with controlled MediaQueryList events; native OS settings and a browser-process restart were not changed by these checks.

## Intent, constraints and unique recommendations — November 18, 2026

The final backend suite passed **72 tests**, with one optional full-corpus Ollama integration test skipped, in 36.13 seconds. Coverage includes natural-language examples, AND/OR grouping and parentheses, exclusions, optional qualifications, strict/inclusive numeric comparisons, experience bounds and scoped experience, exact result counts after deduplication, owner permissions, malicious model proposals, filename-only false positives, and the existing 200-file queue lifecycle. AI sales mentions receive limited ratings and cannot satisfy a four-star AI requirement without technical evidence. Developer roles require corresponding work evidence.

The isolated real-model check in [intent-search-validation.json](intent-search-validation.json) passed all three combined-condition scenarios using `qwen2.5:3b` and `nomic-embed-text` at a 4,096-token context. It returned two qualifying profiles, collapsed a duplicate, excluded a sales engineer, and returned zero for an explicit request for three unique profiles. Actual search times were 28.941, 17.276 and 36.145 seconds, including model loading, interpretation, embedding and bounded reranking where applicable. This is a small synthetic-corpus smoke test, not a claim of universal query accuracy.

The separate 500-document check used real SQLite/Chroma and deterministic embeddings. It verified all 500 qualifying unique documents before returning the requested five, taking 0.429 seconds cold and 0.143 seconds warm. Those numbers exclude language-model inference and do not predict large PDF throughput. Temporary stores were isolated from the user's library.

The query-normalized embedding calibration was remeasured against the existing labeled corpus and held-out paraphrases, with no false positives or negatives in those samples. The deployed profile records query expansion version 3. New unknown paraphrases can still be omitted when their requirements cannot be verified. Date-only employment histories are not converted into asserted experience totals.

Browser validation covers 12 literal-highlighting cases, 11 existing workspace checks, and 10 intent-search checks: precise ratings, per-requirement evidence/page links, optional qualification explanations, numeric-filter highlighting, stale-result clearing, count-policy messages and backend rejection of invalid ratings. These checks use synthetic UI data and nonmutating API requests.

Tested November 17, 2026 with Python 3.11.9, ChromaDB 1.5.9, FastAPI 0.163.1, `nomic-embed-text`, and `qwen2.5:3b`.

Hardware reported by Windows: Intel Core Ultra 7 255H, Intel Graphics, 16,571,895,808 bytes physical RAM (about 15.4 GiB). No dedicated graphics card was reported. These measurements are a small-document smoke test on the actual host, not a throughput or large-library guarantee.

| Real-model operation | Elapsed time |
|---|---:|
| Index a short leave policy | 1.768 seconds |
| Keyword search | 0.005 seconds |
| Semantic search | 1.299 seconds |
| Hybrid search | 0.912 seconds |
| Retrieve and answer with a verified citation | 9.446 seconds |

Context: 4,096 tokens; default retrieval limit: 5 documents; inference serialized; models unloaded after requests. Semantic query `paid time off` retrieved the annual-leave policy. The generated answer selected `Employees receive twenty days of annual paid leave.` and passed exact source verification.

`python -m pytest -q`: **35 tests passed**, plus one opt-in real-model test skipped by default. Coverage includes whole-word/phrase search, false-positive acronym matching, ranking priority, contextual semantic synonyms, threshold overrides and model-specific calibration, per-owner permissions, empty results, unsupported model claims, file changes/deletions, replacement rollback, invalid inputs, DOCX extraction, scanned-PDF handling, multiple uploads, Ollama outages, and upload limits.

Run [scripts/benchmark.py](scripts/benchmark.py) with `python -m scripts.benchmark` to repeat the real-model check. The machine-readable run is saved to `benchmark-result.json` locally. Reproducible installed package versions are recorded in [requirements-lock.txt](requirements-lock.txt).

Browser verification: selected a TXT and CSV together; both indexed with individual success messages. Hybrid search displayed source cards and highlighted matches. The real local model answered the annual-leave question using a verified sentence with a source ID. The matching-page text preview opened successfully.

## Search relevance correction and Everlume branding

The supplied Everlume Solutions logo is displayed unchanged; the local asset's SHA-256 matches the attachment. Page title, company heading, navy controls, and orange accents now identify the company.

Before the correction, five new regression cases failed: `AI` and `ML Engineer` received a full keyword score from email/HTML text, and multi-word queries returned partial matches. They now pass with complete-word boundaries and phrase-first ranking. Truncated keywords such as `eligib` are intentionally excluded in keyword mode.

The actual `nomic-embed-text` model was measured on 13 synthetic documents with five primary queries and three additional paraphrases. Calibration took about 2.4 seconds on this host. All eight measured queries selected their labeled semantic positives and excluded the labeled negatives after context-specific calibration. Additional paraphrases were excluded from threshold fitting. This is a small development evaluation, not a guarantee for unseen company documents.

| Intent | General semantic threshold | With recognized technical context |
|---|---:|---:|
| Agentic AI | 0.7562 | 0.7562 |
| ML Engineer | 0.7396 | 0.6889 |
| AI Engineer | 0.6826 | 0.5952 |
| AI | 0.6459 | 0.5641 |

The opt-in real-model integration test passed in 53.71 seconds: it indexed all 13 documents into isolated Chroma storage, then asserted the exact labeled result set for all eight queries in both hybrid and semantic modes (16 actual API searches). It did not touch the normal document library.

Nine automated browser assertions passed for the production highlighter: acronym boundaries, case-insensitive matches, multi-word phrases, Unicode boundaries, line breaks, safe text rendering, natural-language stopwords, and no invented highlights for semantic synonyms. Matching words such as `Engineer` remain valid literal highlights; `ML` inside `HTML` does not.

Detailed measurements: [relevance-calibration-report.json](relevance-calibration-report.json). Deployed settings: [backend/relevance-calibration.json](backend/relevance-calibration.json).

## Automatic sessions, ratings and 200-file management

The updated suite passed **43 tests**, with the opt-in real-model relevance test skipped in the default run. It completed in 44.82 seconds on this host. New tests verify local-only session bootstrap, HttpOnly cookies, cross-origin rejection, disabled bootstrap in multi-user API mode, owner-scoped library filtering/pagination, metadata edits, evidence reasons and five-point ratings, upload limits, cancellation, durable failed-source retry and crash recovery.

The 200-file lifecycle test sent 200 individual file requests, let the actual background worker index every file into isolated persistent Chroma storage, checked the fourth library page, bulk-deleted all 200 records and verified an empty library. Embeddings were deterministic test fixtures; model speed for 200 substantial files was not measured.

Live browser validation used the actual local Ollama model to upload and index two sample documents through the new upload center. The queue reached 2/2 ready, the library count increased by two, search rendered five source cards with reasons and 4.9/5 relevance ratings, and a sample file was previewed, renamed and recategorized. The two temporary documents were then removed using their specific IDs. Other user documents were not targeted by the smoke test.

Browser checks: nine highlighter assertions and eleven new workspace assertions passed. There is no access-token input, and `document.cookie` does not reveal the session credential. Responsive layout checks at a 390-pixel viewport showed no document-wide horizontal overflow in Discover, Document library, or Upload center.

A live search on this Windows machine using local Ollama for Python in General completed in 28.512 seconds and returned one qualifying unique result, matching the backend qualified count. This verifies the live path, not a comparative speed benchmark; local model interpretation and reranking still contribute latency.

## Reduced search latency � November 19, 2026

Ordinary search now skips advisory chat interpretation and chat-only tie-breaking by default. The deterministic parser, embeddings, all-document scan, evidence validation, filters, ratings, deduplication, and complete result list remain active. SEARCH_AI_ENRICHMENT=true restores optional chat assistance; sourced answers retain enrichment. EMBED_KEEP_ALIVE=5m keeps the lightweight embedding model warm; chat models still unload after generation.

All 100 automated tests passed (one optional corpus test skipped) in 73.87 seconds. A strengthened chat-call regression test also passed separately. Live Python / General / Hybrid / Any-skill searches on this Windows machine took 5.860 seconds initially and 0.372 seconds when repeated, versus the earlier 28.512-second measurement for the same query and dataset. Both returned the same one qualifying document ID as before and made no advisory chat calls. These are individual local measurements, not a guarantee for every query or library size. No user documents were modified.

## General document questions � November 19, 2026

Question retrieval no longer treats conversational wording as mandatory skills. Focused tests cover education, employers, locations, procedures, summaries, comparisons, source isolation, unsupported answers, filler-word ranking, later-document education passages, and empty-model evidence fallback. Explicit numeric, role, and exclusion filters retain strict validation. The live question What education do these candidates have? in Digital Marketing returned the two actual education passages with page-2 sources: Tourism and Hospitality Management / IHM Bhubaneswar, and Electrical Engineering / Techno Main Salt Lake. Answers remain source-checked excerpts; general comparison quality and completeness remain bounded by retrieval and model context.

## Conversational single-candidate recommendations � November 19, 2026

The exact live request i have to select one from digital marketing dataset suggest me one now returns one source and names MAHASWETA SARKAR, citing marketing-team leadership, marketing strategy/execution, and product marketing evidence on page 2. Selection counts recognize select, choose, pick, and suggest me in addition to Top N. Question-topic hits no longer claim all query words matched or receive complete-keyword scores. Candidate display headings use a separate verbatim verifier from normalized identity fingerprints. The full suite passed 135 tests, one optional corpus test skipped, in 34.73 seconds.

## Unified model-driven assistant � November 19, 2026

The local Ollama production adapter now routes Search and Ask through one structured intent plan. The model interprets arbitrary wording; deterministic backend checks retain dataset scope, literal subject provenance, roles, Boolean filters, numerical limits, exclusions and result counts. Count/list operations use verified metadata. Factual answers use per-source structured claims, exact citation options, independent entailment checking, and deterministic quantity/evaluation guards. Invalid or insufficient evidence fails closed. Older adapters without structured understanding retain their compatibility path.

The complete suite passed 162 tests with one optional corpus test skipped. Sixteen dedicated unified-pipeline tests passed after the final matching-summary change. Real-Ollama validation used an isolated temporary four-document library. It correctly listed both Marketing resumes, answered education for both people with citations, returned the AI engineering profile while excluding the AI sales profile under a four-star filter, and summarized supported comparison facts while requesting missing assessment criteria. The strengthened real-model smoke script completed successfully.

In the final synthetic run, local timings were 14.635 seconds for a new listing interpretation, 25.923 seconds for a two-source education answer, 5.873 seconds for the constrained skill search, and 29.148 seconds for a verified comparison. Prior warm runs were faster; these are individual measurements, not service-level guarantees. Interpretation caching avoids repeating that model call for identical query/dataset inputs. Both chat and embedding models can stay warm for five minutes, configurable to zero for immediate release.

A separate small-model draft incorrectly ranked a Bachelor's degree above a Master's degree during development. The final implementation rejects unsupported comparative scales and invented numerical values, with deterministic regression coverage. Model-based entailment remains fallible; source links and partial answer-coverage indicators remain visible. General answers are based on uploaded documents and bounded retrieved evidence, not unrestricted world knowledge or exhaustive reasoning over the whole library.

Final regression check — November 20, 2026: 163 tests passed, one optional test skipped, in 54.95 seconds. Seventeen focused shared-pipeline assertions cover the final validation changes. A live education question against the actual Digital Marketing uploads returned both Ayush Verma''s Tourism and Hospitality Management degree (2019) and Mahasweta Sarkar''s Electrical Engineering qualification (2023), citing page 2 of each document. This live request took 35.876 seconds, illustrating that full model composition/verification can remain slow on the target hardware. Ordinary skill search returns an immediate verified matching-document summary after intent/retrieval, while Ask can request a fuller generated answer.
## General AI routing — 20 November 2026

Live interface verification confirmed automatic General AI routing, no document cards, and a cleared loader after completion. A short RAG question initially produced an incorrect acronym expansion. The general system prompt now includes this application's Retrieval-Augmented Generation context; a fresh real-model call correctly explained retrieval of context for generation. This is a prompt correction, not model training or a guarantee of general factual accuracy.

- Full automated suite: **176 passed, 1 skipped**, 66.54 seconds. Tests cover general mode bypassing retrieval, automatic/manual routing, bounded dataset-scoped history, authentication, invalid plans, hybrid source separation, and document follow-up context without inferred mandatory skills.
- Browser checks: AI mode/conversation behavior **9 passed**; existing highlighting **12**, themes **29**, and all-results pagination **6** passed.
- Actual local `qwen2.5:3b` checks used an isolated temporary library: general ML explanation, conversational example, resume count after general chat, AI-engineer skills advice, and hybrid comparison routed successfully. General/routing sequences took approximately 5–28 seconds per request in these runs; timing varies with response length and load.
- Final actual-model hybrid check returned the uploaded degree quotation with `[S1]` and a separate general interview-advice section in **35.39 seconds**. No user documents were added or changed by these checks.
- An initial model run incorrectly classified a count question as hybrid; routing instructions and examples were tightened. Another run attached general advice to a valid resume quote despite model entailment approval. Hybrid document claims now render exact verified quotations, deduplicated by source and quote; a regression test covers that failure.
- Routing remains model-dependent and general knowledge is not independently fact-checked or live web knowledge. Manual mode selection is available. No model training was performed.

