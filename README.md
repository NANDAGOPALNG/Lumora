# LUMORA

**Your knowledge, connected and searchable.**

An AI-powered knowledge management platform that turns scattered documents and repositories into a searchable, conversational knowledge base, with source-cited answers grounded in your own content.

<br />

<div align="center">

<img src="docs/diagrams/Lumora Banner.png" alt="Lumora Banner" />

![Next.js](https://img.shields.io/badge/Next.js-16-000000?style=flat-square&logo=nextdotjs&logoColor=white)
![React](https://img.shields.io/badge/React-19-61DAFB?style=flat-square&logo=react&logoColor=black)
![TypeScript](https://img.shields.io/badge/TypeScript-5-3178C6?style=flat-square&logo=typescript&logoColor=white)
![Tailwind CSS](https://img.shields.io/badge/Tailwind_CSS-4-06B6D4?style=flat-square&logo=tailwindcss&logoColor=white)
![FastAPI](https://img.shields.io/badge/FastAPI-009688?style=flat-square&logo=fastapi&logoColor=white)
![Python](https://img.shields.io/badge/Python-3.12-3776AB?style=flat-square&logo=python&logoColor=white)
![PostgreSQL](https://img.shields.io/badge/PostgreSQL-4169E1?style=flat-square&logo=postgresql&logoColor=white)
![Qdrant](https://img.shields.io/badge/Qdrant-DC244C?style=flat-square&logo=qdrant&logoColor=white)
![Gemini](https://img.shields.io/badge/Google_Gemini-8E75B2?style=flat-square&logo=googlegemini&logoColor=white)

[Overview](#overview) · [Features](#key-features) · [Architecture](#architecture) · [Getting Started](#getting-started) · [API](#api-overview) · [Status](#integrations-and-current-status) · [Roadmap](#roadmap)

</div>

---



## Overview

Organizational knowledge rarely lives in one place. It is spread across PDFs, Word files, Markdown notes, and code repositories. Traditional storage only helps if you know where to look, and keyword search only helps if you remember the exact words used in the source.

Lumora connects those pieces. Users upload documents or sync a GitHub repository into a **workspace**; Lumora extracts the text, splits it into chunks, embeds them, and indexes them. Questions are then answered through a retrieval-augmented generation (RAG) pipeline:

1. **Hybrid retrieval** combines semantic (vector) search in Qdrant with PostgreSQL full-text search, fused with Reciprocal Rank Fusion.
2. A **cross-encoder reranker** re-scores the candidates against the question.
3. The top passages are assembled into a numbered context and passed to **Google Gemini**, which is instructed to answer only from that context.
4. Answers come back with **source citations** that point to the exact documents and chunks used.

Everything is scoped to the signed-in user's workspaces, and the same retrieval pipeline powers both the standalone Search page and AI Chat.

> **Project status:** Lumora is under active development and has not been deployed. See [Integrations and Current Status](#integrations-and-current-status) for exactly what works today.

---

## Key Features

| Area | What is implemented |
|---|---|
| **Google sign-in** | The frontend uses Google Identity Services; the backend verifies the Google ID token (signature, issuer, audience, expiry) with `google-auth`, creates the user on first login, and issues its own JWT access token. |
| **Workspaces** | A "Personal Workspace" is created on first login. Workspaces can be created, renamed, and deleted; deleting one also removes its stored files and vectors. |
| **Document upload & management** | Upload PDF, DOCX, TXT, and Markdown files (default limit 20 MB). List, inspect, delete, and re-index documents. Document status moves through `Uploaded`, `Processing`, `Indexed`, and `Failed`. |
| **Processing & chunking** | Text extraction per file type, deterministic whitespace cleanup, then paragraph-aware chunking with configurable size and overlap (defaults: 1000 / 150 characters). |
| **Vector embeddings** | `BAAI/bge-m3` embeddings (1024 dimensions, normalized) via `sentence-transformers`, stored in a Qdrant collection using cosine distance. |
| **Semantic search** | Dense retrieval over Qdrant, filtered by workspace (and optionally a single document). |
| **Hybrid retrieval** | Dense and keyword retrieval run concurrently and are fused with Reciprocal Rank Fusion. Keyword retrieval uses PostgreSQL full-text search. |
| **Reranking** | A `sentence-transformers` cross-encoder (default `BAAI/bge-reranker-base`, configurable) re-scores fused candidates. |
| **AI chat** | RAG chat using Gemini through the `google-genai` SDK, behind a provider interface (`BaseLLMProvider`). Prior turns in a conversation are used to understand follow-up questions. |
| **Source citations** | Responses include structured source metadata (filename, chunk index, score, content). The chat UI renders `[n]` markers in answers as clickable references and lists the sources beneath. |
| **Conversation management** | Conversations and messages are persisted per user. Users can list, reopen, continue, and delete conversations. |
| **GitHub integration** | Connect a repository with a personal access token and sync its supported files into a workspace, with incremental updates. See [Integrations](#integrations-and-current-status). |
| **Responsive app shell** | Sidebar navigation, mobile navigation, breadcrumbs, loading and error states, and toast notifications. |
| **Light and dark themes** | System, light, and dark themes via `next-themes`, selectable in Settings. |

---



## Architecture

Lumora is a Next.js single-page-style frontend talking to a FastAPI backend over REST. The backend owns authentication, ingestion, retrieval, and generation. PostgreSQL stores relational data and chunk text; Qdrant stores vectors.

```mermaid
flowchart LR
    User([User])

    subgraph Client["Frontend"]
        FE["Next.js app<br/>React, Tailwind, TanStack Query"]
    end

    subgraph Backend["FastAPI backend"]
        API["REST API /api/v1"]
        AUTH["Auth<br/>Google ID token + JWT"]
        ING["Ingestion pipeline<br/>parse, clean, chunk"]
        EMB["Embedding engine<br/>BGE-M3"]
        RET["Hybrid retrieval<br/>dense + keyword + RRF"]
        RER["Cross-encoder reranker"]
        GEN["Prompt builder +<br/>Gemini provider"]
        CON["Connector service"]
    end

    subgraph Data["Data stores"]
        PG[("PostgreSQL<br/>users, workspaces, documents,<br/>chunks, conversations, connectors")]
        QD[("Qdrant<br/>knowledge_chunks")]
        FS[/"Local file storage"/]
    end

    subgraph External["External services"]
        GID["Google Identity"]
        GEM["Gemini API"]
        GH["GitHub REST API"]
    end

    User --> FE
    FE -->|"Bearer JWT"| API
    FE -.->|"sign-in"| GID
    API --> AUTH
    AUTH -.->|"verify ID token"| GID
    API --> ING
    ING --> FS
    ING --> EMB
    EMB --> QD
    ING --> PG
    API --> RET
    RET --> QD
    RET --> PG
    RET --> RER
    RER --> GEN
    GEN --> GEM
    GEN --> PG
    API --> CON
    CON -->|"fetch files"| GH
    CON --> ING
```

### Document ingestion workflow

Uploading a file and indexing it are two separate calls. The frontend's upload queue performs the upload, then calls re-index. Indexing runs inside the re-index request, with CPU-bound embedding work moved off the event loop.

```mermaid
flowchart TD
    A["Upload file<br/>POST /documents/upload"] --> B{"Extension, content type,<br/>and size valid?"}
    B -- No --> X["415 or 413 error"]
    B -- Yes --> C["Save file under a UUID-based name<br/>Create Document row: Uploaded"]
    C --> D["Re-index<br/>POST /documents/{id}/reindex"]
    D --> E["Status: Processing"]
    E --> F["Extract text<br/>PDF, DOCX, TXT, MD"]
    F --> G["Clean whitespace"]
    G --> H["Paragraph-aware chunking"]
    H --> I["Embed chunks with BGE-M3"]
    I --> J["Replace Chunk rows in PostgreSQL"]
    J --> K["Replace vectors in Qdrant"]
    K --> L["Status: Indexed"]
    F -. "any failure" .-> M["Status: Failed"]
    I -. "any failure" .-> M
    K -. "any failure" .-> M
```

Embeddings are generated before existing chunks are replaced, so a failed re-index leaves the previous chunks and vectors intact.

### Question-answering workflow

```mermaid
sequenceDiagram
    actor U as User
    participant FE as Next.js
    participant API as FastAPI
    participant PG as PostgreSQL
    participant QD as Qdrant
    participant RR as Reranker
    participant LLM as Gemini

    U->>FE: Ask a question
    FE->>API: POST /api/v1/chat
    API->>API: Verify JWT, workspace ownership, conversation ownership
    API->>PG: Load prior messages
    API->>API: Normalize query
    par Dense retrieval
        API->>QD: Embed query and search vectors
    and Keyword retrieval
        API->>PG: Full-text search over chunks
    end
    API->>API: Fuse results with RRF
    API->>PG: Load text for vector-only hits
    API->>RR: Re-score candidates
    RR-->>API: Ranked chunks
    API->>API: Build numbered context
    API->>LLM: Grounded prompt with history and context
    LLM-->>API: Answer
    API->>PG: Save user and assistant messages
    API-->>FE: Answer, conversation id, sources
    FE-->>U: Answer with citations
```

### Design documentation

The original design documents live in [`docs/`](docs). They describe the intended design and may be ahead of or behind the code; the source is authoritative.

- [Product Requirements (PRD)](docs/Lumora_PRD.md)
- [Software Requirements (SRS)](docs/Lumora_SRS.md)
- [High-Level Design (HLD)](docs/Lumora_HLD.md)
- [Low-Level Design (LLD)](docs/Lumora_LLD.md)
- [Database Design (DDD)](docs/Lumora_DDD.md)
- [API Specification](docs/Lumora_API_Specification.md)
- [API Integration Guide](docs/API_Integration_Guide.md)
- Diagrams: [`docs/diagrams/`](docs/diagrams), including [Overall System Architecture](docs/diagrams/Overall%20System%20Architecture.drawio.png), [RAG Pipeline](docs/diagrams/RAG%20Pipeline.drawio.png), and [Entity Relationship Diagram](docs/diagrams/Entity%20Relationship%20Diagram.png)

---

## Technology Stack

| Category | Technologies |
|---|---|
| **Frontend** | Next.js 16 (App Router), React 19, TypeScript, Tailwind CSS 4, Radix UI, shadcn/ui-style components, TanStack Query, next-themes, Motion, Sonner, Lucide icons |
| **Backend** | Python 3.12+, FastAPI, Uvicorn, SQLAlchemy 2 (async), Pydantic v2 and pydantic-settings, Alembic, `requests` |
| **Database** | PostgreSQL (asyncpg for the app, psycopg2 for Alembic); SQLite via aiosqlite as a development fallback and for the test suite |
| **Vector database** | Qdrant (`qdrant-client`), collection `knowledge_chunks`, 1024 dimensions, cosine distance |
| **AI and ML** | BAAI BGE-M3 embeddings and BGE reranker through `sentence-transformers`; Google Gemini through `google-genai`; `pypdf` and `python-docx` for extraction |
| **Authentication** | Google Identity Services (frontend), `google-auth` ID-token verification, JWT via `python-jose` |
| **Development & testing** | `uv` (backend), `pnpm` (frontend), pytest, Vitest with Testing Library and jsdom, ESLint, Ruff, Black |
| **Deployment** | No deployment configuration is committed yet. See [Deployment](#deployment). |

---

## Project Structure

```text
Lumora/
├── backend/
│   ├── main.py                  # FastAPI app, CORS, error envelope, router registration
│   ├── pyproject.toml           # Dependencies (managed with uv; see uv.lock)
│   ├── alembic.ini
│   ├── alembic/versions/        # Database migrations
│   ├── app/
│   │   ├── api/v1/              # Routers: auth, workspace, document, search, chat, connectors
│   │   ├── auth/                # Google ID-token verifier, JWT manager, auth dependencies
│   │   ├── config/              # Pydantic settings
│   │   ├── connectors/          # Base connector, GitHub connector, Google Drive connector
│   │   ├── database/            # Declarative base, async engine and session
│   │   ├── embeddings/          # BGE-M3 embedding engine
│   │   ├── generation/          # RAG prompt builder
│   │   ├── ingestion/           # Parsers (pdf, docx, md, txt), cleaner, chunker, pipeline
│   │   ├── llm/                 # LLM provider interface and Gemini provider
│   │   ├── models/              # SQLAlchemy models
│   │   ├── repositories/        # Data-access layer
│   │   ├── retrieval/           # Query rewriter, dense, keyword, hybrid, reranker, context builder
│   │   ├── schemas/             # Pydantic request/response models
│   │   ├── services/            # Business logic: documents, search, chat, workspaces, connectors
│   │   ├── storage/             # Local file storage
│   │   └── vector_store/        # Qdrant wrapper
│   └── tests/                   # pytest suite
├── frontend/
│   ├── app/                     # Next.js routes: (auth)/login, (app)/ dashboard, workspaces,
│   │                            #   documents, chat, search, integrations, settings
│   ├── components/              # UI by feature: auth, chat, documents, search, workspaces, ...
│   ├── hooks/                   # TanStack Query hooks and client state
│   ├── lib/                     # API client and per-resource API modules, session handling
│   ├── types/                   # Shared TypeScript types
│   └── tests/                   # Vitest suites
├── docs/                        # Design documents and diagrams
├── .env.example                 # Backend environment template
└── LICENSE
```

---

## Getting Started

### Prerequisites

- **Python 3.12+** and [**uv**](https://docs.astral.sh/uv/)
- **Node.js 20+** and [**pnpm**](https://pnpm.io/)
- A **PostgreSQL** database. Hybrid search uses PostgreSQL full-text functions, so PostgreSQL is recommended even for local development.
- A **Qdrant** instance (Qdrant Cloud or self-hosted) and its URL
- A **Google OAuth client ID** for Google sign-in
- A **Gemini API key** for chat

### 1. Clone the repository

```bash
git clone <your-repository-url>
cd Lumora
```

### 2. Backend setup

```powershell
cd backend
uv sync
```

Create the environment file from the template and fill in your values (see [Environment Variables](#environment-variables)):

```powershell
# Windows PowerShell
Copy-Item ..\.env.example .env
```

```bash
# macOS / Linux
cp ../.env.example .env
```

Apply the database migrations (run from `backend/`):

```bash
uv run alembic upgrade head
```

Start the API server:

```bash
uv run uvicorn main:app --reload
```

The API is now available at `http://localhost:8000`. The interactive API docs are at `http://localhost:8000/docs`, and a health check is at `http://localhost:8000/health`.

**Qdrant:** set `QDRANT_URL` (and `QDRANT_API_KEY` for a secured instance). The `knowledge_chunks` collection and its payload indexes are created automatically on first use. If an existing collection has a different vector size or distance, Lumora refuses to use it rather than modifying it.

**Models:** the embedding and reranker models are loaded lazily through `sentence-transformers` on first use, so the first indexing or search request is slower and needs the model files to be available.

### 3. Frontend setup

```powershell
cd frontend
pnpm install
```

Create `frontend/.env.local` (see [Environment Variables](#environment-variables)):

```bash
NEXT_PUBLIC_API_BASE_URL=http://localhost:8000
NEXT_PUBLIC_GOOGLE_CLIENT_ID=<your-google-oauth-client-id>
```

Start the development server:

```bash
pnpm dev
```

Open `http://localhost:3000`. The backend's default `CORS_ORIGINS` already allows this origin.

---

## Environment Variables

> **Never commit `.env` files or real secrets.** The root `.gitignore` excludes `.env` and `.env.*` (except `.env.example`). Frontend variables prefixed `NEXT_PUBLIC_` are embedded in the browser bundle, so never put secrets in them.

### Backend (`backend/.env`, copied from `.env.example`)

| Variable | Purpose | Required | Example / default |
|---|---|---|---|
| `SECRET_KEY` | Signing key for JWT access tokens (at least 32 characters in production) | **Yes** | `<long-random-string>` |
| `GOOGLE_CLIENT_ID` | Google OAuth client ID used to verify ID tokens | **Yes** | `<id>.apps.googleusercontent.com` |
| `DATABASE_URL` | PostgreSQL connection string. Required in production; outside production it falls back to a local SQLite file | Recommended | `postgresql://user:password@localhost:5432/lumora` |
| `QDRANT_URL` | Qdrant endpoint. Indexing and search fail without it | **Yes** for indexing/search | `http://localhost:6333` |
| `QDRANT_API_KEY` | Qdrant API key, if the instance requires one | Optional | `<qdrant-api-key>` |
| `GEMINI_API_KEY` | Gemini API key used by chat | **Yes** for chat | `<gemini-api-key>` |
| `GEMINI_MODEL_NAME` | Gemini model used for answers | Optional | `gemini-3.6-flash` (default) |
| `ENVIRONMENT` | `development`, `staging`, or `production`. Production enables fail-fast config checks | Optional | `development` (default) |
| `CORS_ORIGINS` | Comma-separated browser origins allowed to call the API | Optional | `http://localhost:3000` (default) |
| `ALGORITHM` | JWT signing algorithm | Optional | `HS256` (default) |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | JWT lifetime | Optional | `30` (default) |
| `DOCUMENT_STORAGE_PATH` | Directory for uploaded files | Optional | `storage/documents` (default) |
| `MAX_DOCUMENT_SIZE_MB` | Maximum upload size | Optional | `20` (default) |
| `CHUNK_SIZE` | Target chunk size in characters | Optional | `1000` (default) |
| `CHUNK_OVERLAP` | Overlap between chunks in characters | Optional | `150` (default) |
| `EMBEDDING_MODEL_NAME` | Embedding model | Optional | `BAAI/bge-m3` (default) |
| `EMBEDDING_BATCH_SIZE` | Embedding batch size | Optional | `32` (default) |
| `RERANKER_MODEL_NAME` | Cross-encoder reranker model (defined in settings, not in `.env.example`) | Optional | `BAAI/bge-reranker-base` (default) |
| `HOST`, `PORT` | Present in settings and `.env.example`; the dev command above sets host and port through Uvicorn | Optional | `0.0.0.0`, `8000` |
| `APP_NAME`, `APP_VERSION`, `APP_DESCRIPTION` | API metadata shown in the OpenAPI docs | Optional | see `.env.example` |
| `OPENAI_API_KEY` | Defined in settings but not used by any current code path | Optional | leave empty |

### Frontend (`frontend/.env.local`)

The repository has no frontend env template; create this file yourself.

| Variable | Purpose | Required | Example |
|---|---|---|---|
| `NEXT_PUBLIC_API_BASE_URL` | Base URL of the backend, without a trailing path | **Yes** | `http://localhost:8000` |
| `NEXT_PUBLIC_GOOGLE_CLIENT_ID` | Google OAuth client ID for the sign-in button | **Yes** | `<id>.apps.googleusercontent.com` |
| `NEXT_PUBLIC_MAX_UPLOAD_MB` | Client-side upload size pre-check (the server limit is authoritative) | Optional | `20` (default) |

---

## API Overview

All application routes are served under `/api/v1` and, except sign-in, require an `Authorization: Bearer <token>` header. Errors use a consistent envelope: `{"success": false, "error": {"code": "...", "message": "..."}}`.

Interactive documentation is generated by FastAPI at **`/docs`** (Swagger UI) and **`/redoc`** on the running backend. The design-time contract is in [`docs/Lumora_API_Specification.md`](docs/Lumora_API_Specification.md).

| Group | Endpoint | Description |
|---|---|---|
| **Service** | `GET /`, `GET /health` | Welcome message and health check |
| **Auth** | `POST /api/v1/auth/google` | Exchange a Google ID token for a Lumora access token |
| | `GET /api/v1/auth/me` | Current user profile |
| | `POST /api/v1/auth/logout` | Validates the session; tokens are stateless and discarded client-side |
| **Workspaces** | `GET /api/v1/workspaces` | List the user's workspaces |
| | `POST /api/v1/workspaces` | Create a workspace |
| | `PATCH /api/v1/workspaces/{workspace_id}` | Rename a workspace |
| | `DELETE /api/v1/workspaces/{workspace_id}` | Delete a workspace and its documents |
| **Documents** | `POST /api/v1/documents/upload` | Upload a file (multipart: `workspace_id`, `file`) |
| | `GET /api/v1/documents?workspace_id=...` | List documents in a workspace |
| | `GET /api/v1/documents/{document_id}` | Get one document |
| | `DELETE /api/v1/documents/{document_id}` | Delete a document, its chunks, and its vectors |
| | `POST /api/v1/documents/{document_id}/reindex` | Parse, chunk, embed, and index a document |
| **Search** | `POST /api/v1/search` | Run the retrieval pipeline and return context plus sources (no LLM call) |
| **Chat** | `POST /api/v1/chat` | Ask a question; returns the answer, `conversation_id`, and sources |
| | `GET /api/v1/chat/history` | List the user's conversations, newest first |
| | `GET /api/v1/chat/{conversation_id}` | A conversation with its messages |
| | `DELETE /api/v1/chat/{conversation_id}` | Delete a conversation |
| **Connectors** | `POST /api/v1/connectors/github` | Validate a token and connect a GitHub repository to a workspace |
| | `GET /api/v1/connectors?workspace_id=...` | List a workspace's connectors |
| | `POST /api/v1/connectors/{connector_id}/sync` | Sync a GitHub connector |
| | `DELETE /api/v1/connectors/{connector_id}` | Remove a connector |
| | `POST /api/v1/connectors/google-drive`, `POST /api/v1/connectors/{connector_id}/sync/google-drive` | Backend-only Drive endpoints; see [Integrations](#integrations-and-current-status) |

Search and chat requests accept `query`, `workspace_id`, an optional `document_id` to narrow scope, and `top_k` (default 5, maximum 50).

---

## AI and Retrieval Pipeline

The pipeline is implemented as small, single-purpose components under `backend/app`, composed by `SearchService` and `ChatService`.

| # | Stage | Implementation |
|---|---|---|
| 1 | **Ingestion** | `DocumentService` stores the upload under a UUID-based filename, records a `Document`, and on re-index runs the pipeline below. Existing chunks and vectors are replaced, not appended. |
| 2 | **Text extraction** | PDF via `pypdf` (per page, **no OCR**, so scanned pages yield no text); DOCX via `python-docx` (paragraphs; images ignored); TXT and Markdown read as UTF-8 text (Markdown is kept as raw text). |
| 3 | **Chunking** | Whitespace-normalizing cleaner, then deterministic paragraph-aware chunking: paragraphs are packed up to `CHUNK_SIZE`, over-long paragraphs are split at word boundaries, and adjacent chunks share up to `CHUNK_OVERLAP` characters where possible. This is structure-based, not semantic, chunking. |
| 4 | **Embedding generation** | `BAAI/bge-m3` through `sentence-transformers`: 1024-dimension, normalized vectors, batched, with the model loaded once per process. |
| 5 | **Vector storage** | Qdrant collection `knowledge_chunks` (cosine distance). The payload holds IDs, filename, chunk index, and file type; chunk text stays in PostgreSQL. |
| 6 | **Keyword retrieval** | PostgreSQL full-text search over `chunks.content` using `websearch_to_tsquery` and `ts_rank` (English configuration), scoped to the workspace. |
| 7 | **Semantic retrieval** | The query is embedded and searched in Qdrant, filtered by workspace and optionally by document. |
| 8 | **Hybrid combination** | Dense and keyword retrieval run concurrently. Results are fused with **Reciprocal Rank Fusion** (`k = 60`, equal weights) and deduplicated by chunk. Text for vector-only hits is loaded from PostgreSQL; vectors whose chunk row no longer exists are dropped. |
| 9 | **Reranking** | A `sentence-transformers` `CrossEncoder` scores each (query, chunk) pair and sorts by relevance. Reranking runs off the event loop. |
| 10 | **Context construction** | The reranked chunks are formatted as numbered blocks, `[n] filename (chunk i, source: type)`, alongside a parallel list of source metadata. |
| 11 | **Answer generation** | `RagPromptBuilder` instructs the model to answer only from the context, say so when the context is insufficient, and cite sources by number. Prior conversation turns are included as context only, never as a source of facts. `GeminiProvider` sends the prompt to the configured Gemini model. |
| 12 | **Source citations** | The response returns the ordered `sources` list with each answer. The UI turns `[n]` markers into references to those sources. |

Query handling before retrieval is deterministic (trim and collapse whitespace); no LLM rewrites the query. User and assistant messages are saved only after generation succeeds, so a failed generation does not leave a half-recorded turn.

---

## Integrations and Current Status

| Integration | Status | Details |
|---|---|---|
| **Google sign-in** | Working | ID-token flow end to end (frontend button, backend verification, JWT session). |
| **GitHub** | Working | Connect a repository using a personal access token, then sync. Lumora reads the repository's default branch, selects files with supported extensions (`pdf`, `docx`, `txt`, `md`), skips common build/vendor directories (such as `node_modules` and `dist`), and indexes them through the normal pipeline. Re-syncs are incremental: new files are added, changed files (by Git blob SHA) are re-indexed, and files removed from the repository are removed from the workspace. |
| **Google Drive** | **Under development, not usable from the UI** | The backend has Drive API support (validating a token, discovering files, exporting Google Docs/Sheets/Slides to ingestible formats, incremental sync). It expects a short-lived OAuth access token supplied with each request. There is **no Google OAuth consent/callback or refresh flow**, so Lumora cannot obtain that token itself. The Integrations page shows Drive as "OAuth setup required" with no connect action. Do not treat Drive as production-ready. |
| **Notion** | Not implemented | Mentioned in the data-model notes only. |

**Credential handling for connectors:** GitHub (and Drive) tokens are supplied per request and are **not stored** in the database, logged, or returned. This means GitHub sync currently asks for the token each time. Secure persistent credential storage is on the [roadmap](#roadmap).

Other current limitations:

- Indexing runs inside the re-index request rather than in a background job queue.
- Uploaded files are stored on the local filesystem (development-oriented storage).
- The dashboard's summary cards and "recent activity" panel are layout placeholders and are not yet populated with data.
- PDFs without an embedded text layer (scans) cannot be indexed because there is no OCR step.

---

## Testing

### Backend (pytest)

From `backend/`:

```bash
uv run pytest
```

`tests/conftest.py` supplies throwaway `SECRET_KEY` and `GOOGLE_CLIENT_ID` values, so the suite runs without a `.env` file. Most tests run against SQLite. A small PostgreSQL-only suite (full-text search, foreign-key behavior, unique indexes) is skipped unless you point it at a **disposable** database:

```powershell
# Windows PowerShell
$env:LUMORA_TEST_POSTGRES_URL = "postgresql://postgres:postgres@localhost:5432/lumora_test"
uv run pytest tests/test_wave7_postgres.py
```

The tests cover authentication and token handling, cross-user access isolation, upload limits, connector flows (GitHub and Drive), sync reconciliation, concurrency and failed-reindex behavior, and CORS and production-settings checks.

### Frontend (Vitest)

`package.json` has no `test` script, so run Vitest directly from `frontend/`:

```bash
pnpm exec vitest run
```

Lint and production build:

```bash
pnpm lint
pnpm build
```

The frontend suites use Testing Library with jsdom and a fake backend, covering the API client, auth and session handling, documents, search, chat, workspaces, and connector token safety.

> Pass/fail counts are intentionally not reported here; run the commands above to see current results.

---



## Security Considerations

Lumora has not undergone a formal security review, audit, or certification. The following reflects what the code does.

- **Authentication:** Google ID tokens are verified on the backend with `google-auth` (signature, issuer, audience, expiry). Lumora then issues its own signed JWT access token (30-minute default lifetime, no refresh token). Logout is stateless: the token is discarded by the client.
- **Authorization:** Protected routes require a Bearer token; tokens with an invalid signature, wrong type, non-UUID subject, or unknown user are rejected. Access is scoped to the owner: workspaces, documents, conversations, and connectors are looked up by the authenticated user, and other users' resources return "not found" rather than "forbidden".
- **Workspace isolation in retrieval:** Dense and keyword retrieval always filter by `workspace_id`; an optional `document_id` narrows the scope further but never replaces it.
- **Browser session:** The frontend stores only the access token, in `sessionStorage`, and re-fetches the profile from `/auth/me`. Like any browser storage it is readable by injected scripts, which is why the token is short-lived.
- **CORS:** Only the configured origins are allowed, with no credentialed requests (authentication uses the `Authorization` header, not cookies).
- **Environment variables:** Secrets are read from `.env` (git-ignored). In production the backend refuses to start without `DATABASE_URL` and with a `SECRET_KEY` shorter than 32 characters.
- **Connector credentials:** GitHub and Drive tokens are request-provided and are not persisted, logged, or returned. The frontend token field is a password input that is cleared after each request.
- **File validation:** Uploads are limited to `pdf`, `docx`, `txt`, and `md` by extension, with a soft content-type check and a size limit (default 20 MB, enforced by reading at most one byte past the limit). Stored filenames derive from a server-generated UUID rather than the client filename, and writes outside the storage root are refused. File contents are not inspected beyond parsing.
- **Error handling:** Unhandled exceptions are logged server-side and returned to clients as a generic 500 without internal details.

---

## Roadmap

**Implemented**

- [x] Google sign-in with JWT sessions
- [x] Workspaces with per-user isolation
- [x] Upload, processing, chunking, and re-indexing of PDF, DOCX, TXT, and Markdown
- [x] BGE-M3 embeddings in Qdrant
- [x] Hybrid retrieval (dense + PostgreSQL full-text) with Reciprocal Rank Fusion
- [x] Cross-encoder reranking
- [x] Gemini-powered chat with source citations and persisted conversations
- [x] GitHub repository connector with incremental sync
- [x] Light and dark themes, responsive app shell
- [x] Backend and frontend automated test suites

**Planned**

- [ ] Google Drive OAuth integration (consent, callback, token refresh) and a Drive connect flow in the UI
- [ ] Secure, persistent connector credential management (instead of per-request tokens)
- [ ] Additional knowledge-source integrations (for example Notion)
- [ ] Background indexing jobs instead of in-request processing
- [ ] Object storage for uploaded files
- [ ] Improved conversation persistence and management (for example titles)
- [ ] Live dashboard metrics and activity feed
- [ ] Dockerized local setup, CI, and a finalized deployment configuration
- [ ] Production observability (structured logging, metrics, tracing)
- [ ] Advanced enterprise administration (team workspaces, roles and permissions)

---

## Contributing

Lumora is a personal project, but feedback and suggestions are welcome.

1. Open an issue to describe a bug or idea before starting larger changes.
2. Fork the repository and create a feature branch.
3. Keep changes focused, and add or update tests where relevant (`uv run pytest` for the backend, `pnpm exec vitest run` for the frontend).
4. Run `pnpm lint` for frontend changes, and Ruff/Black for backend changes.
5. Open a pull request describing what changed and why.

Never commit `.env` files or credentials.

---

## License

The repository contains a [`LICENSE`](LICENSE) file, but it is currently empty, so **no license has been specified yet**. Until one is added, all rights are reserved by the author by default.