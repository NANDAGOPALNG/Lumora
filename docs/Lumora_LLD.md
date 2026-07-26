Lumora – Low Level Design (LLD)
Version: 1.0
Author: Nanda Gopal D
Project: KnowledgeOS – Enterprise AI Knowledge Platform

Table of Contents
Introduction
Folder Structure
Backend Design
Frontend Design
Module Design
Database Access Layer
Connector Framework
Retrieval Pipeline
API Layer
Middleware
Background Jobs
Configuration
Error Handling
Logging
Security
Design Patterns
Future Extensibility

1. Introduction
The Low-Level Design (LLD) describes the internal implementation details of KnowledgeOS. It defines the project structure, software modules, responsibilities, interfaces, communication patterns, and coding standards required to build the application.
The architecture follows a modular service-oriented approach with separation of concerns to ensure maintainability, scalability, and extensibility.

2. Project Folder Structure
Lumora/

│
├── frontend/
│
├── backend/
│
├── docs/
│
├── docker/
│
├── tests/
│
├── .github/
│
├── README.md
│
└── docker-compose.yml

3. Backend Folder Structure
backend/

app/

├── api/

├── services/

├── repositories/

├── models/

├── schemas/

├── connectors/

├── retrieval/

├── embeddings/

├── reranker/

├── middleware/

├── workers/

├── utils/

├── config/

└── main.py

4. Frontend Folder Structure
frontend/

app/

components/

hooks/

contexts/

services/

types/

lib/

styles/

public/

5. Backend Module Design
Authentication Service
Responsibilities
Verify Google OAuth tokens
Create user accounts
Generate JWT
Validate sessions
Dependencies
Google OAuth
User Repository
Methods
login()

verify_google_token()

generate_jwt()

get_current_user()

Workspace Service
Responsibilities
Create workspace
Update workspace
Delete workspace
Retrieve workspace
Methods
create_workspace()

update_workspace()

delete_workspace()

get_workspace()

Document Service
Responsibilities
Upload files
Validate file types
Store metadata
Trigger indexing
Methods
upload_document()

delete_document()

get_document()

reindex_document()

Chat Service
Responsibilities
Receive query
Call retrieval engine
Generate response
Save conversation
Methods
chat()

save_message()

get_history()

Search Service
Responsibilities
Query preprocessing
Hybrid retrieval
Metadata filtering
Reranking
Methods
search()

retrieve()

rerank()

build_context()

Connector Service
Responsibilities
Register connector
Synchronize connector
Parse data
Index documents
Methods
connect()

sync()

disconnect()

parse()

6. Repository Layer
Purpose
Separate database operations from business logic.
Repositories
UserRepository

WorkspaceRepository

DocumentRepository

ConversationRepository

ConnectorRepository
Example
class UserRepository:

    create_user()

    get_user()

    update_user()

    delete_user()

7. Database Models
Models
User

Workspace

Document

Chunk

Conversation

Message

Connector
Relationships
User

↓

Workspace

↓

Document

↓

Chunk

8. Schema Layer
Pydantic Schemas
UserCreate

UserResponse

WorkspaceCreate

DocumentUpload

ChatRequest

ChatResponse
Purpose
Validation
Serialization
API Documentation

9. Connector Framework
BaseConnector

↓

PDFConnector

GitHubConnector

GoogleDriveConnector

NotionConnector
BaseConnector Interface
connect()

sync()

parse()

index()

10. Retrieval Engine
Components
Query Rewriter

↓

Embedding Generator

↓

Hybrid Retriever

↓

Metadata Filter

↓

Cross Encoder Reranker

↓

Context Builder
Responsibilities
Retrieve relevant chunks
Improve relevance
Reduce hallucination
Prepare LLM context

11. Embedding Module
Embedding Model
BGE-M3
Methods
embed_document()

embed_query()
Output
Dense vectors

12. Reranker Module
Model
BAAI BGE-Reranker
Method
rerank()
Purpose
Improve retrieval quality before LLM generation.

13. LLM Provider Layer
Provider Interface
class BaseLLMProvider:

    generate()
Implementations
GeminiProvider

OpenRouterProvider
Responsibilities
Prompt execution
Response generation
Token usage
Error handling

14. API Layer
/auth

/workspaces

/upload

/search

/chat

/connectors
Each API follows
API

↓

Service

↓

Repository

↓

Database

15. Middleware
Authentication
JWT Verification
Logging
Request Logger
Error Handling
Global Exception Handler
Rate Limiting
Request Limiter

16. Background Workers
Tasks
Document Parsing
Chunk Generation
Embedding Generation
GitHub Sync
Google Drive Sync
Future
Scheduled Re-indexing

17. Frontend Components
Pages
Login

Dashboard

Chat

Upload

Documents

Connectors

Settings
Shared Components
Navbar

Sidebar

Chat Window

Upload Card

Search Bar

Citation Card

Loader

18. React Hooks
useAuth()

useChat()

useDocuments()

useWorkspace()

useSearch()

19. State Management
Global State
Authentication

Workspace

Theme

User
Server State
React Query

20. Configuration
Environment Variables
DATABASE_URL

GOOGLE_CLIENT_ID

GOOGLE_CLIENT_SECRET

JWT_SECRET

QDRANT_URL

QDRANT_API_KEY

GEMINI_API_KEY

OPENROUTER_API_KEY

REDIS_URL

21. Error Handling
Authentication Errors
400
401
403
File Errors
415
413
Search Errors
500
503
LLM Errors
429
500

22. Logging Strategy
Levels
INFO

WARNING

ERROR

CRITICAL
Log Sources
Authentication
Upload
Search
Chat
Connectors

23. Security Design
Authentication
Google OAuth
Authorization
JWT
Data Protection
Workspace Isolation
Secrets
Environment Variables
File Upload
Validation
Rate Limiting
Enabled
HTTPS
Mandatory

24. Design Patterns Used
Repository Pattern
Service Layer Pattern
Dependency Injection
Factory Pattern
Strategy Pattern (LLM Provider)
Adapter Pattern (Connectors)
Singleton (Configuration)

25. Coding Standards
Backend
Python 3.12+
PEP 8
Type hints
Async endpoints
Black formatter
Ruff linting
Frontend
TypeScript
ESLint
Prettier
Functional Components
React Hooks

26. Testing Strategy
Backend
Unit Tests
Integration Tests
API Tests
Frontend
Component Tests
UI Tests
End-to-End
Authentication
Upload
Chat
Search

27. Future Extensibility
Additional Connectors
Slack
Jira
Confluence
Additional LLMs
Claude
GPT
Llama
Storage
S3
Azure Blob
Deployment
Kubernetes
Observability
Prometheus
Grafana
Langfuse

28. Development Sequence
Phase 1
Authentication
Workspace
Database
Phase 2
Upload
Parsing
Chunking
Phase 3
Embeddings
Qdrant
Search
Phase 4
Chat
Gemini Integration
Phase 5
GitHub Connector
Phase 6
Google Drive Connector
Phase 7
Deployment
