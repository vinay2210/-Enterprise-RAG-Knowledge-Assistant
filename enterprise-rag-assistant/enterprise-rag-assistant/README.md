# Enterprise RAG Knowledge Assistant

A production-style Retrieval-Augmented Generation app that syncs documents from a
Google Drive folder, indexes them into a vector database, and answers natural-language
questions with page-level citations.

This README is written for someone setting this up for the first time in VS Code.
Follow it top to bottom — don't skip steps.

---

## 1. Architecture

```
                     ┌─────────────────────┐
                     │   Google Drive       │
                     │  "AI Knowledge Base" │
                     └──────────┬───────────┘
                                │ poll every N seconds (APScheduler)
                                ▼
   ┌───────────────────────────────────────────────────────────┐
   │                     FastAPI Backend                       │
   │                                                             │
   │  Drive Sync ──▶ Download ──▶ Extract Text ──▶ Clean Text   │
   │       │                                          │          │
   │       │                                          ▼          │
   │       │                                   Chunk Document    │
   │       │                                          │          │
   │       │                                          ▼          │
   │       │                                 Generate Embeddings │
   │       │                                          │          │
   │       │                                          ▼          │
   │       │                                Store in ChromaDB    │
   │       │                                                     │
   │  SQLite (Documents, Chunks, Chat history, OAuth tokens)     │
   │                                                             │
   │  Chat API ──▶ Retriever ──▶ ChromaDB (vector search)        │
   │       │                                                     │
   │       ▼                                                     │
   │     LLM (OpenAI / Anthropic / Ollama) ──▶ Answer + Citations│
   └───────────────────────────┬───────────────────────────────┘
                                │ REST (JSON)
                                ▼
                     ┌─────────────────────┐
                     │  React (Vite) UI     │
                     │  Chat + doc sidebar  │
                     └─────────────────────┘
```

**Why this stack:**
- **FastAPI** — async, typed, auto-generates OpenAPI docs at `/docs`, which is genuinely useful while you're building and testing this by hand.
- **SQLite** — zero setup for local dev; the code uses SQLAlchemy so swapping to Postgres later is a one-line `DATABASE_URL` change, no code changes.
- **ChromaDB** — a persistent, local vector database. No external service to run, unlike Qdrant/Weaviate which need a Docker container.
- **sentence-transformers (BGE)** for embeddings by default — free and runs on CPU, so you can get this fully working tonight without an API key. OpenAI embeddings are a config toggle away if you want higher quality.
- **React + Vite** — much faster dev server than Next.js for a small SPA like this, and simpler for a first-timer to reason about.

---

## 2. Project structure

```
enterprise-rag-assistant/
├── backend/
│   ├── app/
│   │   ├── main.py              # FastAPI app, CORS, scheduler, routes
│   │   ├── config.py            # all env vars, loaded once
│   │   ├── database.py          # SQLAlchemy engine/session
│   │   ├── models.py            # ORM: Document, DocumentChunk, ChatSession, UserToken
│   │   ├── schemas.py           # Pydantic request/response contracts
│   │   ├── auth/google_oauth.py # Google login/callback/refresh
│   │   ├── drive/
│   │   │   ├── drive_service.py # thin Google Drive API wrapper
│   │   │   └── sync.py          # diff Drive vs DB, trigger pipeline
│   │   ├── rag/
│   │   │   ├── extractor.py     # PDF/DOCX/TXT/MD -> text per page
│   │   │   ├── chunker.py       # token-aware chunking with overlap
│   │   │   ├── embeddings.py    # local (BGE) or OpenAI embeddings
│   │   │   ├── vector_store.py  # ChromaDB wrapper
│   │   │   ├── pipeline.py      # orchestrates the full ingestion flow
│   │   │   ├── retriever.py     # vector search for chat
│   │   │   └── llm.py           # OpenAI / Anthropic / Ollama answer generation
│   │   └── api/                 # FastAPI routers (auth, drive, chat, documents)
│   ├── tests/                   # pytest unit tests
│   ├── requirements.txt
│   └── .env.example
├── frontend/
│   ├── src/
│   │   ├── App.jsx               # chat UI + document sidebar
│   │   ├── api.js                # backend API client
│   │   └── main.jsx
│   ├── package.json
│   └── .env.example
├── docker-compose.yml            # optional containerized run
└── README.md                     # you are here
```

---

## 3. Prerequisites

Install these before you start:

1. **Python 3.11+** — check with `python3 --version`
2. **Node.js 18+** — check with `node --version`
3. **VS Code** with the Python and ES7+ React extensions (optional but helpful)
4. **Git** (optional, for version control)
5. A **Google account** (for the Drive OAuth part)
6. An **OpenAI API key** *or* an **Anthropic API key** *or* [Ollama](https://ollama.com) installed locally (for the LLM that generates answers)

---

## 4. Step-by-step setup

### Step 1 — Open the project in VS Code

Unzip the project and open the `enterprise-rag-assistant` folder in VS Code
(`File > Open Folder`).

### Step 2 — Set up the backend

Open a terminal in VS Code (`` Ctrl+` `` / `` Cmd+` ``) and run:

```bash
cd backend
python3 -m venv venv

# Activate the virtual environment
source venv/bin/activate        # macOS/Linux
venv\Scripts\activate           # Windows

pip install -r requirements.txt
```

This will take a few minutes the first time — `sentence-transformers` pulls in PyTorch.

Copy the example env file and open it:

```bash
cp .env.example .env
```

Leave everything default for now **except** the LLM provider section — you need at
least one of these to generate answers:

- **Easiest for testing:** get an OpenAI key at https://platform.openai.com/api-keys,
  set `OPENAI_API_KEY=sk-...` and leave `LLM_PROVIDER=openai`.
- **No API cost:** install [Ollama](https://ollama.com), run `ollama pull llama3.1`,
  then set `LLM_PROVIDER=ollama` in `.env`.
- You can leave `EMBEDDING_PROVIDER=local` — it needs no API key and runs on your CPU.

### Step 3 — Set up Google OAuth (for automatic Drive sync)

You can skip this step initially and use the "Upload file" button in the UI to test
the RAG pipeline end-to-end without Google at all. Come back to this when you want
the real Drive sync working.

1. Go to https://console.cloud.google.com/ and create a new project (or pick an existing one).
2. Go to **APIs & Services > Library**, search for **Google Drive API**, and click **Enable**.
3. Go to **APIs & Services > OAuth consent screen**:
   - User type: External (unless you have a Google Workspace).
   - Fill in app name, your email, and add yourself as a **test user** on the "Test users" screen — this matters, Google will block login otherwise while the app is unpublished.
4. Go to **APIs & Services > Credentials > Create Credentials > OAuth client ID**:
   - Application type: **Web application**.
   - Authorized redirect URI: `http://localhost:8000/api/auth/google/callback`
   - Copy the generated **Client ID** and **Client Secret**.
5. Paste them into `backend/.env`:
   ```
   GOOGLE_CLIENT_ID=xxxxxxxx.apps.googleusercontent.com
   GOOGLE_CLIENT_SECRET=xxxxxxxx
   ```

### Step 4 — Run the backend

Still inside `backend/` with the venv activated:

```bash
uvicorn app.main:app --reload
```

You should see logs confirming the database was initialized and the sync scheduler
started. Visit **http://localhost:8000/docs** — you should see the interactive API
docs (Swagger UI). This is the fastest way to sanity-check the backend independent
of the frontend.

> **First-run note:** the first time you send a chat message, `sentence-transformers`
> and `tiktoken` will each download a small model/vocab file from the internet. This
> is a one-time download, cached locally afterward.

### Step 5 — Set up and run the frontend

Open a **second terminal** (keep the backend running in the first one):

```bash
cd frontend
npm install
cp .env.example .env
npm run dev
```

Visit **http://localhost:5173**. You should see the chat UI with an empty document
sidebar and a "Connect Google Drive" button.

### Step 6 — Try it end to end

**Fastest path (no Google setup needed):** click **"+ Upload file"** in the sidebar
and pick any PDF, DOCX, TXT, or Markdown file. Watch its status go
`pending → downloading → extracting → chunking → embedding → ready`. Once it says
`ready`, ask a question about it in the chat box.

**Full path with Google Drive:** click **"Connect Google Drive"**, sign in, grant
access. The app auto-creates a folder called **"AI Knowledge Base"** in your Drive.
Because the app needs permission to read files you add to that folder, it will request
Drive read access during consent. Drop a PDF into that folder from drive.google.com,
then click **"Sync now"** (or wait for the background poller — every 60s by default).
Watch it appear and index.

**File-scoped search:** type `@` followed by (part of) a filename in the chat box,
e.g. `@handbook.pdf what is the leave policy?` — this restricts retrieval to that
file only. Omit the `@mention` to search across every indexed document.

---

## 5. How the RAG pipeline actually works

### Chunking strategy (500+ page documents)

We chunk **per page, not per document**:

1. Extract text page-by-page (PDF/DOCX give us real or synthesized page boundaries).
2. For each page, count tokens with `tiktoken` and split into windows of
   `CHUNK_SIZE_TOKENS` (default 500) with `CHUNK_OVERLAP_TOKENS` (default 75) tokens
   of overlap between consecutive windows.
3. Every chunk carries its exact page number.

This matters for two reasons:
- **Citations are accurate.** Because we never merge text across pages before
  chunking, we can always tell the user exactly which page an answer came from.
- **Memory stays bounded.** We never hold the entire 500-page document as one string
  in memory for chunking — we process and discard one page's tokens at a time.

### Batching & memory management for large documents

- **Extraction** streams page-by-page from `pypdf`; a single corrupted page doesn't
  fail the whole document, it's just skipped.
- **Embedding generation** is batched (128 chunks at a time) so a 500-page document
  that produces thousands of chunks never sends one giant request to the embedding
  model / API, and peak memory stays flat regardless of document size.
- **Vector storage** is also batched (256 chunks per Chroma `upsert` call).
- Large intermediate objects (`file_bytes`, `pages`) are explicitly deleted (`del`)
  as soon as the next stage no longer needs them.

### Retrieval optimization

- Embeddings are cosine-normalized at index time, and ChromaDB is configured with
  `hnsw:space: cosine`, which is the standard, fast approximate-nearest-neighbor
  setup for semantic search at this scale.
- File-scoped search (`@filename`) uses a Chroma metadata `where` filter, so it's a
  filtered ANN search, not a full re-scan.
- `top_k` (default 6) is tunable per-request — the chat UI could later expose this
  as a "more context" toggle.

### Handling document updates

`drive/sync.py` compares each file's `modifiedTime` against what's stored in SQLite.
If a file was edited in Drive, we delete its old vectors (`vector_store.delete_document`)
and re-run it through the full pipeline — this is the **incremental indexing** bonus
feature, and it's also what makes **delete-vectors-on-file-deletion** work (same
function, invoked when a file disappears from the Drive folder or is removed via the UI).

### Error handling

Every stage in `pipeline.py` is wrapped; failures set `Document.status = FAILED` with
`error_message` populated, rather than crashing the sync job or leaving a document
stuck in an ambiguous state. Specific cases handled explicitly:
- Unsupported file type → status `UNSUPPORTED`, file is still shown in the UI so you
  know it was seen and skipped, and why.
- Corrupted PDF/DOCX → caught in `extractor.py`, surfaced as a clear error message.
- Empty document (e.g. scanned PDF with no text layer) → status `EMPTY`.
- Embedding/API failures → caught in `pipeline.py`, retried on next sync cycle.
- OAuth/auth failures → `google_oauth.get_valid_credentials` returns `None`, sync is
  skipped with a warning log instead of raising.

---

## 6. API overview

Full interactive docs live at `http://localhost:8000/docs` once the backend is running.

| Endpoint | Purpose |
|---|---|
| `GET /api/auth/google/login` | Redirects to Google's consent screen |
| `GET /api/auth/status` | Is Drive connected? which account? |
| `POST /api/auth/google/disconnect` | Revoke local tokens |
| `POST /api/drive/sync` | Trigger an immediate sync |
| `GET /api/drive/documents` | List all indexed documents + status |
| `DELETE /api/drive/documents/{id}` | Remove a document and its vectors |
| `POST /api/documents/upload` | Manually upload a file (bypasses Drive) |
| `POST /api/chat` | Ask a question, get an answer + citations |
| `POST /api/chat/stream` | Same, but streamed token-by-token |
| `GET /api/chat/sessions/{id}/history` | Conversation history |

---

## 7. Running tests

```bash
cd backend
source venv/bin/activate
pytest tests/ -v
```

Covers chunking behavior (page-boundary preservation, overlap, empty input) and
text extraction (empty-document detection, markdown tag stripping).

---

## 8. Running with Docker (optional)

If you'd rather not install Python/Node locally:

```bash
docker compose up --build
```

This builds and runs both services with the same env files. Note: the local
embedding model download is significantly slower inside a fresh container the
first time.

---

## 9. Design decisions worth knowing (for your writeup / demo)

- **Single-user, single-folder scope**, matching the assignment ("create or locate
  'AI Knowledge Base' folder"). `UserToken` is a one-row table by design — extending
  to multi-tenant just means keying it by a real user ID; nothing else in the
  pipeline changes.
- **Provider abstraction for embeddings and LLMs** (`embeddings.py`, `llm.py`) means
  you can demo this fully offline and free (local embeddings + Ollama) or swap to
  OpenAI/Anthropic for quality with a single `.env` change — no code edits.
- **Status is always visible, never silent.** Every document shows its exact pipeline
  stage in the UI in near real-time (polled every 5s), which matters a lot when
  you're debugging why a 500-page PDF hasn't shown up as "ready" yet.
- **Background sync doesn't block the API.** `POST /api/drive/sync` returns
  immediately; the actual work happens in a FastAPI `BackgroundTask`, and the
  frontend polls document status rather than waiting on a long HTTP request.

## 10. What I'd add next (bonus features not yet implemented)

- Hybrid search (BM25 + vector) for queries with exact keywords/numbers.
- Cross-encoder re-ranking of the top-K retrieved chunks before they hit the LLM.
- OCR (e.g. Tesseract) fallback for scanned, image-only PDFs.
- Redis/Celery instead of APScheduler for a horizontally-scalable sync worker.
