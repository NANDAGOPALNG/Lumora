# Lumora

**An AI-powered enterprise knowledge platform** that unifies documents, repositories, and external knowledge sources into a single searchable, conversational workspace — grounded in Retrieval-Augmented Generation (RAG) with source citations on every answer.

> **Status: In active development.** This is a work-in-progress build, updated daily. Currently implementing the **database layer** (SQLAlchemy models, Alembic migrations, async session handling). Not yet functional end-to-end — see [Progress](#-progress) below for what's done and what's next.

---

## Overview

Knowledge today is fragmented across PDFs, GitHub repos, Google Drive, Notion, and internal docs. Existing search tools are keyword-based, require knowing *where* to look, and often return irrelevant results.

Lumora solves this by letting users ask natural-language questions and get **grounded, citation-backed answers** synthesized from their own connected knowledge sources — instead of manually digging through scattered files.

### Core Principles
- **Grounded Responses** — every AI answer is backed by retrievable source content
- **Simple UX** — auth, upload, and search require minimal friction
- **Extensible Architecture** — new connectors and AI providers are easy to add
- **Provider Independence** — not locked to a single LLM vendor
- **Production Readiness** — built like a real product, not a notebook demo

---

## Planned Features (v1 / MVP)

- Google OAuth sign-in with JWT session management
- Isolated personal workspace per user
- Document upload (PDF, DOCX, TXT, Markdown) with background processing
- GitHub repository connector for indexing docs/markdown from a repo
- Semantic + hybrid search over indexed content
- Conversational AI chat with citations and confidence indicators
- Chat/conversation history

*Out of scope for v1: team workspaces, billing, RBAC, Slack/Notion/Drive connectors, OCR, mobile app — see the [PRD](docs/Lumora_PRD.md) for the full roadmap.*

---

## Tech Stack

| Layer | Technology |
|---|---|
| Frontend | Next.js 16, React 19, TypeScript, Tailwind CSS, shadcn/ui |
| Backend | FastAPI, SQLAlchemy (async), Alembic, Pydantic Settings |
| Database | PostgreSQL (Neon) in production, SQLite (aiosqlite) for local dev |
| Vector Store | Qdrant Cloud |
| Embeddings | BAAI BGE-M3 |
| Reranker | BAAI BGE-Reranker |
| LLM | Gemini 2.5 Flash (primary), OpenRouter-compatible fallback |
| Cache | Upstash Redis |
| Deployment (target) | Vercel (frontend), Render (backend) |

Full rationale for each choice is in the [SRS](docs/Lumora_SRS.md).

---

## Project Structure

```
Lumora/
├── backend/
│   ├── app/
│   │   ├── config/          # Pydantic Settings, environment config
│   │   ├── database/        # Base model, async session, Alembic migrations
│   │   ├── models/          # SQLAlchemy models: User, Workspace, Document
│   │   └── connectors/      # BaseConnector interface (PDF, GitHub, ...)
│   ├── main.py               # FastAPI entrypoint
│   └── pyproject.toml
├── frontend/
│   ├── app/                  # Next.js app directory
│   └── package.json
├── docs/                     # PRD, SRS, HLD, LLD, DDD, API Spec
├── docker-compose.yml         # (placeholder — not yet configured)
├── Makefile                   # (placeholder — not yet configured)
└── .env.example
```

---

## Progress

- [x] Product Requirements Document (PRD)
- [x] Software Requirements Specification (SRS)
- [x] High-Level Design (HLD)
- [x] Low-Level Design (LLD)
- [x] Detailed Database Design (DDD)
- [x] API Specification
- [x] FastAPI project scaffold + settings/config module
- [x] Base SQLAlchemy models (`User`, `Workspace`, `Document`)
- [ ] **⏳ Currently in progress:** Alembic migrations, async DB session wiring, remaining schema (conversations, chunks/embeddings metadata, connector state)
- [ ] Document upload + processing pipeline
- [ ] Embedding generation + Qdrant integration
- [ ] Retrieval pipeline (hybrid search + reranking)
- [ ] AI chat endpoint with citations
- [ ] Google OAuth + JWT auth
- [ ] GitHub connector
- [ ] Frontend: auth, workspace dashboard, chat UI
- [ ] Deployment (Vercel + Render + Neon + Qdrant Cloud)

---

## Getting Started (local dev)

> Note: setup is still evolving alongside the database work — expect rough edges.

### Backend

```bash
cd backend
cp ../.env.example .env   # then fill in SECRET_KEY at minimum
uv sync                   # or: pip install -e .
uv run uvicorn main:app --reload
```

Defaults to a local SQLite database (`sqlite+aiosqlite:///./lumora.db`) when no `DATABASE_URL` is set in development.

- `GET /` → welcome message
- `GET /health` → service health check

### Frontend

```bash
cd frontend
pnpm install
pnpm dev
```

---

## Documentation

Full design docs live in [`docs/`](docs):

- [Product Requirements (PRD)](docs/Lumora_PRD.md)
- [Software Requirements (SRS)](docs/Lumora_SRS.md)
- [High-Level Design (HLD)](docs/Lumora_HLD.md)
- [Low-Level Design (LLD)](docs/Lumora_LLD.md)
- [Database Design (DDD)](docs/Lumora_DDD.md)
- [API Specification](docs/Lumora_API_Specification.md)

---

## License

See [LICENSE](LICENSE).

---

*Built solo, one commit a day, as a portfolio-grade demonstration of production-oriented AI application engineering.*
