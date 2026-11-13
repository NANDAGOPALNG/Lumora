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
![Jina AI](https://img.shields.io/badge/Jina_AI-009191?style=flat-square&logoColor=white)
![Cloudflare R2](https://img.shields.io/badge/Cloudflare_R2-F38020?style=flat-square&logo=cloudflare&logoColor=white)
![Gemini](https://img.shields.io/badge/Google_Gemini-8E75B2?style=flat-square&logo=googlegemini&logoColor=white)
![Vercel](https://img.shields.io/badge/Vercel-000000?style=flat-square&logo=vercel&logoColor=white)
![Render](https://img.shields.io/badge/Render-46E3B7?style=flat-square&logo=render&logoColor=black)

[Overview](#overview) · [Features](#key-features) · [Architecture](#architecture) · [Getting Started](#getting-started) · [Deployment](#deployment) · [API](#api-overview) · [Status](#integrations-and-current-status) · [Roadmap](#roadmap)

</div>

---

> **About this branch:** `free_deployment` is the branch prepared for running Lumora entirely on free-tier hosting: Vercel, Render, Neon, Qdrant Cloud, and Cloudflare R2, with embeddings and reranking from Jina AI and answers from Gemini. This README describes that branch. The `main` branch is a separate line of development and its setup differs, mainly in where embeddings, reranking, and document storage run, so use the README on `main` when working with it.

## Overview

Organizational knowledge rarely lives in one place. It is spread across PDFs, Word files, Markdown notes, and code repositories. Traditional storage only helps if you know where to look, and keyword search only helps if you remember the exact words used in the source.

Lumora connects those pieces. Users upload documents or sync a GitHub repository into a **workspace**; Lumora extracts the text, splits it into chunks, embeds them, and indexes them. Questions are then answered through a retrieval-augmented generation (RAG) pipeline:

1. **Hybrid retrieval** combines semantic (vector) search in Qdrant with PostgreSQL full-text search, fused with Reciprocal Rank Fusion.
2. A **reranker** (the Jina Reranker API) re-scores the candidates against the question.
3. The top passages are assembled into a numbered context and passed to **Google Gemini**, which is instructed to answer only from that context.
4. Answers come back with **source citations** that point to the exact documents and chunks used.

Everything is scoped to the signed-in user's workspaces, and the same retrieval pipeline powers both the standalone Search page and AI Chat.

> **Project status:** Lumora is under active development. This branch contains the free-tier deployment setup (see [Deployment](#deployment)). See [Integrations and Current Status](#integrations-and-current-status) for exactly what works today.

---

## Key Features

| Area | What is implemented |
|---|---|
| **Google sign-in** | The frontend uses Google Identity Services; the backend verifies the Google ID token (signature, issuer, audience, expiry) with `google-auth`, creates the user on first login, and issues its own JWT access token. |
| **Workspaces** | A "Personal Workspace" is created on first login. Workspaces can be created, renamed, and deleted; deleting one also removes its stored files and vectors. |
| **Document upload & management** | Upload PDF, DOCX, TXT, and Markdown files (default limit 20 MB). List, inspect, delete, and re-index documents. Document status moves through `Uploaded`, `Processing`, `Indexed`, and `Failed`. |
| **Document storage** | Uploaded files are stored in Cloudflare R2 (the production setting) or on local disk for development, each under a server-generated UUID name. Deleting a document or workspace removes its stored files too. |
| **Processing & chunking** | Text extraction per file type, deterministic whitespace cleanup, then paragraph-aware chunking with configurable size and overlap (defaults: 1000 / 150 characters). |
| **Vector embeddings** | `jina-embeddings-v3` embeddings (1024 dimensions) from the Jina AI Embeddings API, stored in a Qdrant collection using cosine distance. No model runs inside the backend. |
| **Semantic search** | Dense retrieval over Qdrant, filtered by workspace (and optionally a single document). |
| **Hybrid retrieval** | Dense and keyword retrieval run concurrently and are fused with Reciprocal Rank Fusion. Keyword retrieval uses PostgreSQL full-text search. |
| **Reranking** | The Jina Reranker API (default `jina-reranker-v2-base-multilingual`, configurable) re-scores fused candidates. |
| **AI chat** | RAG chat using Gemini through the `google-genai` SDK, behind a provider interface (`BaseLLMProvider`). Prior turns in a conversation are used to understand follow-up questions. |
| **Source citations** | Responses include structured source metadata (filename, chunk index, score, content). The chat UI renders `[n]` markers in answers as clickable references and lists the sources beneath. |
| **Conversation management** | Conversations and messages are persisted per user. Users can list, reopen, continue, and delete conversations. |
| **GitHub integration** | Connect a repository with a personal access token and sync its supported files into a workspace, with incremental updates. See [Integrations](#integrations-and-current-status). |
| **Responsive app shell** | Sidebar navigation, mobile navigation, breadcrumbs, loading and error states, and toast notifications. |
| **Light and dark themes** | System, light, and dark themes via `next-themes`, selectable in Settings. |

---



## Architecture

Lumora is a Next.js single-page-style frontend talking to a FastAPI backend over REST. The backend owns authentication, ingestion, retrieval, and generation. PostgreSQL stores relational data and chunk text; Qdrant stores vectors; Cloudflare R2 stores the uploaded files; Jina AI provides embeddings and reranking.

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
        EMB["Embedding client<br/>Jina Embeddings"]
        RET["Hybrid retrieval<br/>dense + keyword + RRF"]
        RER["Reranker client<br/>Jina Reranker"]
        GEN["Prompt builder +<br/>Gemini provider"]
        CON["Connector service"]
    end

    subgraph Data["Data stores"]
        PG[("PostgreSQL<br/>users, workspaces, documents,<br/>chunks, conversations, connectors")]
        QD[("Qdrant<br/>knowledge_chunks")]
        FS[/"Document storage<br/>Cloudflare R2<br/>(local disk in development)"/]
    end

    subgraph External["External services"]
        GID["Google Identity"]
        GEM["Gemini API"]
        GH["GitHub REST API"]
        JINA["Jina AI API"]
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
    EMB -->|"embed text"| JINA
    ING --> PG
    API --> RET
    RET --> QD
    RET --> PG
    RET --> RER
    RER -->|"score pairs"| JINA
    RER --> GEN
    GEN --> GEM
    GEN --> PG
    API --> CON
    CON -->|"fetch files"| GH
    CON --> ING
```

### Document ingestion workflow

Uploading a file and indexing it are two separate calls. The frontend's upload queue performs the upload, then calls re-index. Indexing runs inside the re-index request; embeddings come from the Jina API.

```mermaid
flowchart TD
    A["Upload file<br/>POST /documents/upload"] --> B{"Extension, content type,<br/>and size valid?"}
    B -- No --> X["415 or 413 error"]
    B -- Yes --> C["Store file (R2) under a UUID-based key<br/>Create Document row: Uploaded"]
    C --> D["Re-index<br/>POST /documents/{id}/reindex"]
    D --> E["Status: Processing"]
    E --> R["Read file from storage"]
    R --> F["Extract text<br/>PDF, DOCX, TXT, MD"]
    F --> G["Clean whitespace"]
    G --> H["Paragraph-aware chunking"]
    H --> I["Embed chunks with Jina<br/>(jina-embeddings-v3)"]
    I --> J["Replace Chunk rows in PostgreSQL"]
    J --> K["Replace vectors in Qdrant"]
    K --> L["Status: Indexed"]
    R -. "any failure" .-> M["Status: Failed"]
    F -. "any failure" .-> M
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
    participant EM as Jina Embeddings
    participant QD as Qdrant
    participant RR as Jina Reranker
    participant LLM as Gemini

    U->>FE: Ask a question
    FE->>API: POST /api/v1/chat
    API->>API: Verify JWT, workspace ownership, conversation ownership
    API->>PG: Load prior messages
    API->>API: Normalize query
    par Dense retrieval
        API->>EM: Embed query
        API->>QD: Search vectors
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

The original design documents live in [`docs/`](docs). They describe the intended design and may be ahead of or behind the code; the source is authoritative. They predate this branch's hosted setup, and the diagrams include components (such as Redis) that the current code does not use.

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
| **Backend** | Python 3.12+, FastAPI, Uvicorn, SQLAlchemy 2 (async), Pydantic v2 and pydantic-settings, Alembic, `httpx`, `boto3`, `requests` |
| **Database** | PostgreSQL (Neon in production; asyncpg for the app, psycopg2-binary for Alembic); SQLite via aiosqlite as a development fallback and for the test suite |
| **Vector database** | Qdrant (`qdrant-client`), collection `knowledge_chunks`, 1024 dimensions, cosine distance |
| **Object storage** | Cloudflare R2 through its S3-compatible API (`boto3`); local disk as the development default |
| **AI** | Jina AI Embeddings (`jina-embeddings-v3`, 1024 dimensions) and Jina Reranker (`jina-reranker-v2-base-multilingual`), both called over HTTPS with `httpx`; Google Gemini through `google-genai`; `pypdf` and `python-docx` for extraction |
| **Authentication** | Google Identity Services (frontend), `google-auth` ID-token verification, JWT via `python-jose` |
| **Development & testing** | `uv` (backend), `pnpm` (frontend), pytest, Vitest with Testing Library and jsdom, ESLint, Ruff, Black |
| **Deployment** | Vercel (frontend), Render Free (backend, via [`render.yaml`](render.yaml)), Neon, Qdrant Cloud, Cloudflare R2. See [Deployment](#deployment). |

---

## Project Structure

```text
Lumora/
├── backend/
│   ├── main.py                  # FastAPI app, CORS, error envelope, router registration
│   ├── pyproject.toml           # Dependencies (managed with uv; see uv.lock)
│   ├── alembic.ini
│   ├── scripts/                 # Operator commands for the Qdrant collection (status, init, reset)
│   ├── alembic/versions/        # Database migrations
│   ├── app/
│   │   ├── api/v1/              # Routers: auth, workspace, document, search, chat, connectors
│   │   ├── auth/                # Google ID-token verifier, JWT manager, auth dependencies
│   │   ├── config/              # Pydantic settings
│   │   ├── connectors/          # Base connector, GitHub connector, Google Drive connector
│   │   ├── database/            # Declarative base, async engine and session
│   │   ├── embeddings/          # Jina embedding client (remote API)
│   │   ├── generation/          # RAG prompt builder
│   │   ├── ingestion/           # Parsers (pdf, docx, md, txt), cleaner, chunker, pipeline
│   │   ├── llm/                 # LLM provider interface and Gemini provider
│   │   ├── models/              # SQLAlchemy models
│   │   ├── repositories/        # Data-access layer
│   │   ├── retrieval/           # Query rewriter, dense, keyword, hybrid, reranker, context builder
│   │   ├── schemas/             # Pydantic request/response models
│   │   ├── services/            # Business logic: documents, search, chat, workspaces, connectors
│   │   ├── storage/             # Document storage: local disk and Cloudflare R2
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
├── render.yaml                  # Render Blueprint for the backend
└── LICENSE
```

---

## Getting Started

### Prerequisites

- **Python 3.12+** and [**uv**](https://docs.astral.sh/uv/)
- **Node.js 20+** and [**pnpm**](https://pnpm.io/)
- A **PostgreSQL** database. Hybrid search uses PostgreSQL full-text functions, so PostgreSQL is recommended even for local development.
- A **Qdrant** instance (Qdrant Cloud or self-hosted) and its URL
- A **Jina AI API key** (one key serves embeddings and reranking)
- For production-style document storage, a **Cloudflare R2** bucket (optional for local development, which stores files on disk)
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

**Jina AI:** embeddings and reranking are remote API calls, so no model is downloaded or loaded and the backend needs no ML framework. Set `JINA_API_KEY`; the same key is used for both.

**Document storage:** by default uploads are written to `DOCUMENT_STORAGE_PATH` on local disk, which is fine for development. To use Cloudflare R2 instead, create a private bucket and an R2 API token with Object Read & Write access scoped to that bucket, then set `DOCUMENT_STORAGE_BACKEND=r2` and the `R2_*` variables. The backend refuses to start if R2 is selected but a required variable is missing. Each document is stored under a UUID key (`documents/<document id>.<ext>`), never its original filename. The `storage_path` column holds `r2://documents/...` for R2 documents and an absolute path for local ones, which is how the right provider is chosen; no database migration is involved.

**One embedding model per collection:** the `knowledge_chunks` collection is 1024-dimension cosine, and so are the vectors of other 1024-dimension models, so Qdrant cannot tell them apart; mixing models gives wrong search results without any error. New points therefore carry an `embedding_model` payload field, and `backend/scripts/qdrant_admin.py` can inspect the collection. Run these from `backend/`; they read `QDRANT_URL`, `QDRANT_API_KEY`, `DATABASE_URL`, and `JINA_API_KEY` from `.env`:

```bash
# Read-only: connection, vector size and distance, point count, and which model the stored points say they came from
uv run python -m scripts.qdrant_admin status

# Creates the collection and payload indexes only if they are missing. Never changes anything that exists.
uv run python -m scripts.qdrant_admin init

# Read-only (Qdrant and PostgreSQL SELECT only, plus a few Jina calls): re-embeds a few stored chunks
# and compares them with what is stored, to detect leftover vectors from another model
uv run python -m scripts.qdrant_admin check-vectors --sample 5
```

A brand-new Qdrant cluster needs none of this: the collection is created on the first upload. If `status` or `check-vectors` shows vectors from another model, the one destructive command starts the collection over. It is a dry run unless you add `--execute`:

```bash
# Dry run: prints what it would delete and changes nothing
uv run python -m scripts.qdrant_admin reset

# Real reset: needs the Qdrant host repeated, then asks you to type the collection name
uv run python -m scripts.qdrant_admin reset --execute --confirm-host <your-cluster-host>
```

`reset` deletes **only** the `knowledge_chunks` collection on the cluster in `QDRANT_URL` (every vector in it) and recreates it empty. It does not touch PostgreSQL (documents, chunks), Cloudflare R2 (files), or any other collection. Afterwards, existing documents still have chunk rows but no vectors, so delete them in the app or re-index each one (`POST /api/v1/documents/{id}/reindex`), which re-reads the file from storage and embeds it with Jina. The web application never calls `reset`: it can only create a missing collection or delete the vectors of a single document.

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
| `DATABASE_URL` | PostgreSQL connection string (a Neon string with `sslmode` and `channel_binding` works as pasted). Required in production; outside production it falls back to a local SQLite file | Recommended | `postgresql://user:password@localhost:5432/lumora` |
| `QDRANT_URL` | Qdrant endpoint. Indexing and search fail without it | **Yes** for indexing/search | `http://localhost:6333` |
| `QDRANT_API_KEY` | Qdrant API key. Qdrant Cloud always needs one | Optional locally, **required in production** | `<qdrant-api-key>` |
| `JINA_API_KEY` | Jina AI API key, used for both embeddings and reranking | **Yes** for indexing/search | `<jina-api-key>` |
| `GEMINI_API_KEY` | Gemini API key used by chat | **Yes** for chat (required in production) | `<gemini-api-key>` |
| `GEMINI_MODEL_NAME` | Gemini model used for answers | Optional | `gemini-3.6-flash` (default) |
| `ENVIRONMENT` | `development`, `staging`, or `production`. Production enables fail-fast config checks (see [Deployment](#deployment)) | Optional | `development` (default) |
| `CORS_ORIGINS` | Comma-separated browser origins allowed to call the API. In production it must be set explicitly (the frontend origin, no trailing slash); `*` is rejected | Optional locally, **required in production** | `http://localhost:3000` (default) |
| `ALGORITHM` | JWT signing algorithm | Optional | `HS256` (default) |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | JWT lifetime | Optional | `30` (default) |
| `DOCUMENT_STORAGE_BACKEND` | Where new uploads are stored: `local` or `r2`. Existing documents are always read from the provider that stored them. Production requires `r2` | Optional locally, **required in production** | `local` (default) |
| `DOCUMENT_STORAGE_PATH` | Directory for uploaded files (local backend only) | Optional | `storage/documents` (default) |
| `R2_ACCOUNT_ID`, `R2_ACCESS_KEY_ID`, `R2_SECRET_ACCESS_KEY`, `R2_BUCKET_NAME` | Cloudflare R2 credentials and bucket | **Yes** when the backend is `r2` | `<r2-...>` |
| `R2_ENDPOINT_URL` | Override for the R2 endpoint | Optional | `https://<R2_ACCOUNT_ID>.r2.cloudflarestorage.com` (derived) |
| `MAX_DOCUMENT_SIZE_MB` | Maximum upload size | Optional | `20` (default) |
| `CHUNK_SIZE` | Target chunk size in characters | Optional | `1000` (default) |
| `CHUNK_OVERLAP` | Overlap between chunks in characters | Optional | `150` (default) |
| `EMBEDDING_MODEL_NAME` | Jina embedding model (1024 dimensions) | Optional | `jina-embeddings-v3` (default) |
| `EMBEDDING_BATCH_SIZE` | Embedding batch size | Optional | `32` (default) |
| `JINA_RERANKER_MODEL_NAME` | Jina reranker model | Optional | `jina-reranker-v2-base-multilingual` (default) |
| `JINA_RERANKER_URL` | Jina rerank endpoint | Optional | `https://api.jina.ai/v1/rerank` (default) |
| `JINA_EMBEDDING_URL` | Jina embeddings endpoint (defined in settings, not in `.env.example`) | Optional | `https://api.jina.ai/v1/embeddings` (default) |
| `HOST`, `PORT` | Present in settings and `.env.example`; the dev command above sets host and port through Uvicorn, and on Render the start command uses its assigned `$PORT` | Optional | `0.0.0.0`, `8000` |
| `APP_NAME`, `APP_VERSION`, `APP_DESCRIPTION` | API metadata shown in the OpenAPI docs | Optional | see `.env.example` |
| `OPENAI_API_KEY` | Defined in settings but not used by any current code path | Optional | leave empty |

### Frontend (`frontend/.env.local`)

The repository has no frontend env template; create this file yourself. These values are embedded when the frontend is built, so on Vercel set them before deploying and redeploy after changing them.

| Variable | Purpose | Required | Example |
|---|---|---|---|
| `NEXT_PUBLIC_API_BASE_URL` | Base URL of the backend, without a trailing path | **Yes** | `http://localhost:8000` |
| `NEXT_PUBLIC_GOOGLE_CLIENT_ID` | Google OAuth client ID for the sign-in button | **Yes** | `<id>.apps.googleusercontent.com` |
| `NEXT_PUBLIC_MAX_UPLOAD_MB` | Client-side upload size pre-check (the server limit is authoritative) | Optional | `20` (default) |

---

## Deployment

This branch is set up to run on free tiers. The configuration lives in the repository; nothing in it deploys by itself.

| Part | Service | Notes |
|---|---|---|
| **Frontend** | Vercel (Next.js) | Root Directory `frontend` |
| **Backend** | Render Free (FastAPI, native Python, no Docker) | Configured by [`render.yaml`](render.yaml) |
| **Database** | Neon (PostgreSQL) | Migrations are applied manually, once |
| **Vector database** | Qdrant Cloud | The collection is created on first use |
| **Document storage** | Cloudflare R2 | Accessed only by the backend |
| **Embeddings and reranking** | Jina AI | One API key for both |
| **LLM** | Google Gemini | |

```mermaid
flowchart LR
    User([User]) --> VER["Vercel<br/>Next.js frontend"]
    VER -->|"REST + Bearer JWT"| REN["Render Free<br/>FastAPI backend"]
    VER -.->|"sign-in"| GID["Google Identity"]
    REN -.->|"verify ID token"| GID
    REN --> NEON[("Neon<br/>PostgreSQL")]
    REN --> QC[("Qdrant Cloud<br/>knowledge_chunks")]
    REN --> R2[/"Cloudflare R2<br/>documents"/]
    REN --> JINA["Jina AI<br/>embeddings + reranking"]
    REN --> GEM["Gemini API"]
    REN -.->|"fetch files"| GH["GitHub REST API"]
```

### Backend on Render

`render.yaml` is a Render Blueprint (New, then Blueprint, then pick this repository and the `free_deployment` branch). Secrets are not in the file: Render asks for them once in the dashboard, and generates `SECRET_KEY` itself.

| Setting | Value |
|---|---|
| Root Directory | `backend` |
| Build Command | `uv sync --locked --no-dev` (installs exactly what `uv.lock` pins) |
| Start Command | `uv run --no-sync uvicorn main:app --host 0.0.0.0 --port $PORT` |
| Health Check Path | `/health` (does not touch the database) |
| `PYTHON_VERSION` | `3.12.12` (Render needs a fully qualified version) |
| Auto-deploy | Off; deploy manually from the dashboard |

Set these variables on the service (the full list with defaults is in [Environment Variables](#environment-variables)): `ENVIRONMENT=production`, `DOCUMENT_STORAGE_BACKEND=r2`, `SECRET_KEY`, `DATABASE_URL`, `GOOGLE_CLIENT_ID`, `CORS_ORIGINS`, `R2_ACCOUNT_ID`, `R2_ACCESS_KEY_ID`, `R2_SECRET_ACCESS_KEY`, `R2_BUCKET_NAME`, `JINA_API_KEY`, `QDRANT_URL`, `QDRANT_API_KEY`, `GEMINI_API_KEY`, and `GEMINI_MODEL_NAME`.

With `ENVIRONMENT=production` the backend refuses to start, naming the variable (never its value), if `DATABASE_URL` is missing, `SECRET_KEY` is shorter than 32 characters, `JINA_API_KEY`, `QDRANT_URL`, `QDRANT_API_KEY`, or `GEMINI_API_KEY` is empty, `DOCUMENT_STORAGE_BACKEND` is not `r2`, the R2 credentials are incomplete, or `CORS_ORIGINS` is unset or `*`.

### Database migrations (Neon)

Migrations are deliberately not part of the build or start command, so they can never run twice or by surprise. Apply them once, from your own machine, to Neon's **direct** (non-pooled) connection string. Run from `backend/`:

```powershell
# Windows PowerShell
$env:DATABASE_URL = "<neon-direct-connection-string>"
$env:SECRET_KEY = "x"; $env:GOOGLE_CLIENT_ID = "x"   # only so settings load; Alembic does not use them
uv run alembic current             # prints nothing on a new database
uv run alembic upgrade head --sql  # optional: preview the SQL without connecting
uv run alembic upgrade head
uv run alembic current             # must show the head revision
```

```bash
# macOS / Linux
export DATABASE_URL='<neon-direct-connection-string>' SECRET_KEY=x GOOGLE_CLIENT_ID=x
uv run alembic current && uv run alembic upgrade head && uv run alembic current
```

The environment variable overrides any local `backend/.env`, so check the target first: if `alembic current` or the preview is aimed at the wrong database, stop before running `upgrade`.

### Frontend on Vercel

Create the project with Root Directory `frontend`. The framework preset (Next.js), install command (`pnpm install`, which honors `pnpm-lock.yaml`), and build command (`next build`) are the defaults. Set two environment variables, then deploy:

| Variable | Value |
|---|---|
| `NEXT_PUBLIC_API_BASE_URL` | The Render service URL, for example `https://lumora-api.onrender.com` (no trailing slash and no `/api/v1`) |
| `NEXT_PUBLIC_GOOGLE_CLIENT_ID` | The same Google OAuth client ID as the backend's `GOOGLE_CLIENT_ID` |

Everything prefixed `NEXT_PUBLIC_` is visible to every visitor, so no secret belongs in Vercel.

### Google sign-in and CORS

In the Google Cloud Console, add the Vercel origin (for example `https://your-app.vercel.app`) to the OAuth client's **Authorized JavaScript origins**. The sign-in button uses Google's popup flow, so no redirect URI is needed. If the OAuth consent screen is in "Testing", only listed test users can sign in. Set the same origin as `CORS_ORIGINS` on Render.

### Free-tier behavior

- A Render Free service sleeps after 15 minutes without traffic, so the first request afterwards can take about a minute.
- Its disk is wiped on every deploy, restart, and spin-down, which is why production stores documents in R2 and refuses to start with local storage.
- The free plan has 512 MB of RAM; the backend needs no ML framework or model download, which keeps its footprint small.

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
| | `DELETE /api/v1/documents/{document_id}` | Delete a document, its chunks, its vectors, and its stored file |
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
| 1 | **Ingestion** | `DocumentService` stores the upload (in Cloudflare R2 in production) under a UUID-based key, records a `Document`, and on re-index reads the file back from storage and runs the pipeline below. Existing chunks and vectors are replaced, not appended. |
| 2 | **Text extraction** | PDF via `pypdf` (per page, **no OCR**, so scanned pages yield no text); DOCX via `python-docx` (paragraphs; images ignored); TXT and Markdown read as UTF-8 text (Markdown is kept as raw text). |
| 3 | **Chunking** | Whitespace-normalizing cleaner, then deterministic paragraph-aware chunking: paragraphs are packed up to `CHUNK_SIZE`, over-long paragraphs are split at word boundaries, and adjacent chunks share up to `CHUNK_OVERLAP` characters where possible. This is structure-based, not semantic, chunking. |
| 4 | **Embedding generation** | The Jina Embeddings API (`jina-embeddings-v3`, task `retrieval.passage` for chunks and `retrieval.query` for questions): 1024-dimension vectors, batched, with retries on rate limits and server errors. |
| 5 | **Vector storage** | Qdrant collection `knowledge_chunks` (cosine distance). The payload holds IDs, filename, chunk index, file type, and the embedding model name; chunk text stays in PostgreSQL. |
| 6 | **Keyword retrieval** | PostgreSQL full-text search over `chunks.content` using `websearch_to_tsquery` and `ts_rank` (English configuration), scoped to the workspace. |
| 7 | **Semantic retrieval** | The query is embedded and searched in Qdrant, filtered by workspace and optionally by document. |
| 8 | **Hybrid combination** | Dense and keyword retrieval run concurrently. Results are fused with **Reciprocal Rank Fusion** (`k = 60`, equal weights) and deduplicated by chunk. Text for vector-only hits is loaded from PostgreSQL; vectors whose chunk row no longer exists are dropped. |
| 9 | **Reranking** | The Jina Reranker API scores each (query, chunk) pair and the results are sorted by relevance. It is an async HTTP call; candidates without text are not sent and rank last. |
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
- Uploaded files go to Cloudflare R2 when `DOCUMENT_STORAGE_BACKEND=r2` (the production setting) and to local disk otherwise. Documents stored locally before R2 was enabled stay readable but are not migrated automatically.
- Embeddings and reranking depend on the Jina AI API, so indexing and search need network access and a valid `JINA_API_KEY`.
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

The tests cover authentication and token handling, cross-user access isolation, upload limits, connector flows (GitHub and Drive), sync reconciliation, concurrency and failed-reindex behavior, and CORS and production-settings checks. Jina and R2 are mocked and Qdrant runs in memory, so no test needs credentials or a network connection; the storage, fresh-collection, and Qdrant admin-command tests drive the real upload, indexing, retrieval, and delete code through those fakes.

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
- **CORS:** Only the configured origins are allowed, with no credentialed requests (authentication uses the `Authorization` header, not cookies). In production `CORS_ORIGINS` must be set explicitly and cannot be `*`.
- **Environment variables:** Secrets are read from `.env` (git-ignored). In production the backend refuses to start if `DATABASE_URL` is missing, `SECRET_KEY` is shorter than 32 characters, the Jina, Qdrant, or Gemini settings are empty, document storage is not R2, or `CORS_ORIGINS` is unset or `*`. Configuration errors name the variable but never print its value.
- **Connector credentials:** GitHub and Drive tokens are request-provided and are not persisted, logged, or returned. The frontend token field is a password input that is cleared after each request.
- **File validation:** Uploads are limited to `pdf`, `docx`, `txt`, and `md` by extension, with a soft content-type check and a size limit (default 20 MB, enforced by reading at most one byte past the limit). Stored names (local paths and R2 object keys alike) derive from a server-generated UUID rather than the client filename, and local writes outside the storage root are refused. File contents are not inspected beyond parsing.
- **Document storage:** In production the backend writes files to Cloudflare R2 with credentials from environment variables, which are checked at start-up and kept out of logs and error messages. The application does not issue public or presigned URLs.
- **Destructive Qdrant operations:** The application can only create a missing `knowledge_chunks` collection or delete the vectors of one document. Resetting the collection exists only as the explicit `scripts.qdrant_admin reset` command, which is a dry run by default and needs the cluster host and a typed confirmation to execute.
- **Error handling:** Unhandled exceptions are logged server-side and returned to clients as a generic 500 without internal details.

---

## Roadmap

**Implemented**

- [x] Google sign-in with JWT sessions
- [x] Workspaces with per-user isolation
- [x] Upload, processing, chunking, and re-indexing of PDF, DOCX, TXT, and Markdown
- [x] Jina embeddings in Qdrant, with a model marker on each vector
- [x] Hybrid retrieval (dense + PostgreSQL full-text) with Reciprocal Rank Fusion
- [x] Reranking with the Jina Reranker API
- [x] Cloudflare R2 document storage
- [x] Free-tier deployment configuration (Render Blueprint; Vercel, Neon, Qdrant Cloud, R2)
- [x] Gemini-powered chat with source citations and persisted conversations
- [x] GitHub repository connector with incremental sync
- [x] Light and dark themes, responsive app shell
- [x] Backend and frontend automated test suites

**Planned**

- [ ] Google Drive OAuth integration (consent, callback, token refresh) and a Drive connect flow in the UI
- [ ] Secure, persistent connector credential management (instead of per-request tokens)
- [ ] Additional knowledge-source integrations (for example Notion)
- [ ] Background indexing jobs instead of in-request processing
- [ ] Improved conversation persistence and management (for example titles)
- [ ] Live dashboard metrics and activity feed
- [ ] Dockerized local setup and CI
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