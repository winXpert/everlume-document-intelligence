# Everlume Solutions — Intelligence Workspace

## Simple project guide

Updated: 20 November 2026

### 1. What is this project?

This is a local AI assistant for general questions and uploaded documents. You can ask for an explanation, search resumes, count files in a dataset, compare documented information, or get general guidance alongside document evidence.

The application uses Ollama on your computer. It does not require a paid AI API or model training to answer general questions.

### 2. Start the application

1. Make sure Ollama is running.
2. Open PowerShell in the project folder.
3. Run:

```powershell
.\start.ps1
```

4. Open http://127.0.0.1:8000.
5. Keep the backend running while using the application.

The local browser session connects automatically; there is no token-entry field. For a fresh installation, follow [README.md](./README.md). Initial setup downloads packages and models; normal use runs locally afterward.

### 3. Choose the right AI mode

The **AI mode** dropdown is beside the search controls.

| Mode | What it does | Example |
|---|---|---|
| Auto | Ollama chooses general, document, or hybrid answering. This is the interface default. | `What is machine learning?` |
| General AI | Uses the model's existing knowledge without searching uploads. | `Explain RAG with an example.` |
| Document AI | Searches and answers from the selected dataset, with evidence checks. | `Find AI engineers with 5+ years experience.` |
| Hybrid AI | Shows verified document quotations and a separate section of general guidance. | `Compare these candidates against AI engineering best practices.` |

Enter a question and select **Search** or **Ask AI**. Search can return a matching-document summary; Ask AI requests a fuller answer. Both respect the selected AI mode.

General questions do not need uploaded files. Selecting a dataset does not force Auto to search it for every question. Choose a mode manually if Auto misunderstands your intent.

**General AI** uses model knowledge, which can be incorrect or outdated. **Document AI** provides source references. In **Hybrid AI**, general advice is labelled separately and does not prove a candidate's qualifications.

### 4. Upload files into datasets

1. Open **Upload center**.
2. Select files or drag them into the upload area. You can select up to **200 files per batch**.
3. Enter **Dataset / category**, such as `General`, `Digital Marketing`, `.NET`, or `Angular`.
4. Select **Start upload** and check each file's progress.
5. Open **Document library** to manage indexed files.

You can also use **Choose folder** to select a domain folder. Its folder name becomes the dataset. Select each domain folder separately rather than their common parent.

Supported formats include PDF, DOCX, TXT, CSV, Markdown, JSON, and log files. The default limit is **20 MB per file**. Convert older `.doc` files to DOCX or PDF. Scanned PDFs need OCR before upload; built-in OCR is not included.

Files are indexed one at a time to control memory use. Files already received by the backend can continue processing after the tab closes, while the backend stays running. Files not yet transferred must be selected again to resume. Received queued work can resume after a backend restart.

The application uploads copies; it does not watch the original Windows folders for changes.

### 5. Search a specific dataset

Open **Discover**, select a **Dataset**, and enter your question. Document retrieval uses only that dataset. For example, selecting `.NET` excludes resumes in General, Digital Marketing, and Angular. An empty dataset does not fall back to other datasets.

You do **not** need to repeat the selected dataset in the query. With Digital Marketing selected, try:

- `How many resumes are here?`
- `List candidate names.`
- `Describe their education.`
- `Who has campaign management experience?`

Counts describe indexed files, including separately uploaded duplicate files. They are not necessarily counts of unique people. Search recommendations remove duplicate content and check similar resume versions.

Name listings use verified document headings and source links. A category label alone does not prove a skill.

### 6. Understand the search controls

**AI mode** decides where an answer comes from. **Search method** decides how documents are retrieved. They are separate controls.

| Search method | Meaning |
|---|---|
| Exact keywords | Matches complete words and phrases. `AI` does not match inside `Emails`. |
| Semantic search | Finds related meaning using embeddings and relevance filtering. |
| Hybrid search | Combines keyword matching and semantic retrieval. |

**Skills → Match any skill** is the default: any one requested skill can qualify. More complete matches rank first. Hybrid and Semantic search can also include supported related experience; these results identify skills that could not be verified. **Match all skills** requires all requested skills.

Other explicit conditions still apply:

| Query | Expected check |
|---|---|
| `Python or Java` | Evidence of either skill. |
| `React without Angular` | React evidence and exclusion of verified Angular experience. |
| `AI engineers with 5+ years experience` | Engineering evidence and verified experience meeting the minimum. |
| `Best 3 ML engineers with 4+ stars` | Role relevance, minimum rating, and three qualifying unique results. |

An explicit result count follows the all-or-nothing policy: return that many qualifying unique results or none. Without an explicit count, all qualifying unique documents are returned, subject to the configured minimum, currently one.

Results appear in pages of **20 cards**. Previous and Next navigate the retrieved set without rerunning AI search.

### 7. Read answers and recommendations

Document cards can show:

- Filename, verified candidate name, and document ID.
- Query relevance rating out of five.
- Matching text, source page, and evidence links.
- Reasons for matching and missing preferred qualifications.

Ratings measure relevance to the current query, **not candidate quality or hiring suitability**. Backend rating filters use the numerical value before display rounding. A sales role mentioning AI products does not establish AI engineering experience.

Document answers use retrieved passages and citation checks. Hybrid document findings use exact verified quotations; general guidance appears separately. Source references such as `[S1]` refer to the supplied document sources.

If mandatory requirements cannot be verified, the system does not fill the results with unrelated documents. If sources cannot support an answer, it reports that limitation. Check the original documents when making decisions: even an accurately quoted document can contain incorrect information.

Answers use a bounded selection of evidence to fit the local model's context. When only part of the matching library is cited, the interface shows the coverage. Narrow a question for a closer comparison.

### 8. Ask follow-up questions

You can continue a conversation, for example:

1. `What is machine learning?`
2. `Explain it with a simple example.`

The most recent three exchanges can provide context, within the configured context budget. History stays in the browser tab's memory; it is not a permanent chat archive.

Changing the dataset or AI mode, changing the skill-matching setting, or selecting **New conversation** clears the conversation context. Previous chat messages are not document evidence: document answers retrieve and validate sources again.

### 9. Manage documents and appearance

In **Document library**, filter by filename or category and open previews. You can rename documents, change datasets, replace file contents, or delete selected files. Updating or deleting documents updates their index.

Evidence links open matching pages. PDF page numbers are preserved; DOCX and text formats use extracted text views rather than dependable printed-page layouts.

Choose **Light**, **Dark**, or **System** in the header. The browser remembers the appearance preference. Changing appearance does not reset searches or uploaded files.

### 10. How the system works

**Upload:** extract text → split into chunks → generate embeddings → store metadata and the search index.

**Question:** interpret intent → choose General, Document, or Hybrid mode.

**Document search:** retrieve candidates → check explicit conditions → remove duplicates → rank → enforce result count → show evidence.

| Part | Technology |
|---|---|
| Interface | HTML, CSS, and browser JavaScript |
| Backend | Python and FastAPI |
| Local language model | Ollama, normally `qwen2.5:3b` |
| Embeddings | Ollama, normally `nomic-embed-text` |
| Storage | ChromaDB vectors and SQLite metadata |

Model names, context size, and retrieval limits are configurable for lightweight local operation.

**Prompt engineering** sets model behavior. **RAG (Retrieval-Augmented Generation)** provides retrieved document context without changing model weights. **Fine-tuning** changes model behavior through external training on curated examples; it is not implemented or required here. Future supported models or adapters could be imported into Ollama after compatible external training and evaluation.

### 11. Privacy and limitations

Files, extracted text, and indexes are stored locally in the project's data directory. With the default configuration, AI requests go to the local Ollama service.

Document APIs enforce ownership. The automatic browser session is for a trusted single-user workspace, not a company-wide sign-in system. Keep the data directory and token private. Theme preferences use localStorage; session credentials do not.

- **Wrong automatic mode:** Select General AI, Document AI, or Hybrid AI explicitly.
- **No document results:** Check the selected dataset and the unmet conditions. An empty dataset will not search elsewhere.
- **Cannot verify experience:** The application needs explicit, nonconflicting experience statements; it does not guess totals from employment dates alone.
- **Slow response:** Local generation can take several seconds or longer. A loader stays visible while processing. Response length, model, available memory, and other workloads affect timing.
- **Ollama unavailable:** Start Ollama and check that the configured models are installed, then retry.
- **Unclear or incorrect answer:** Rephrase the question, check citations, or select the intended mode. Small models can misunderstand queries; general knowledge is not independently fact-checked or live web information.

### 12. Validation and further reading

The latest full automated run recorded **176 passed tests and one skipped test**. Browser checks cover AI modes, conversation history, themes, highlighting, and result pagination.

Real local-model checks covered general explanations, follow-ups, dataset counts, skills advice, and hybrid responses. General/routing sequences took approximately **5–28 seconds** in recorded runs. The final hybrid check with an actual source quotation took **35.39 seconds**. These are measured examples, not response-time guarantees.

- [README.md](./README.md): Installation, configuration, and APIs.
- [VALIDATION.md](./VALIDATION.md): Detailed tests, measurements, and known limits.
- [backend/main.py](./backend/main.py): API entry point.
- [frontend/](./frontend/): Interface files.
- [tests/](./tests/): Automated checks.

API reference while running: http://127.0.0.1:8000/docs.

For existing API clients, search and ask still default to document mode for compatibility. Send `query_mode` as `auto`, `general`, `document`, or `hybrid` to override it. Optional `history` accepts up to six `{role, content, dataset}` messages; only messages matching the selected dataset are used.
