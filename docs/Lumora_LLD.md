
# Lumora Low Level Design (LLD)

**Version:** 1.0  
**Author:** Nanda Gopal D  
**Project:** Lumora – Enterprise AI Knowledge Platform

---

## Table of Contents
1. Introduction
2. Project Folder Structure
3. Backend Folder Structure
4. Frontend Folder Structure
5. Backend Module Design
6. Repository Layer
7. Database Models
8. Schema Layer
9. Connector Framework
10. Retrieval Engine
11. Embedding Module
12. Reranker Module
13. LLM Provider Layer
14. API Layer
15. Middleware
16. Background Workers
17. Frontend Components
18. React Hooks
19. State Management
20. Configuration
21. Error Handling
22. Logging Strategy
23. Security Design
24. Design Patterns
25. Coding Standards
26. Testing Strategy
27. Future Extensibility
28. Development Sequence

## 1. Introduction
The Low-Level Design (LLD) describes the internal implementation details of KnowledgeOS. It defines the project structure, software modules, interfaces, responsibilities, communication patterns, and coding standards. The architecture follows a modular service-oriented approach with clear separation of concerns.

## 2. Project Folder Structure
```text
Lumora/
├── frontend/
├── backend/
├── docs/
├── docker/
├── tests/
├── .github/
├── README.md
└── docker-compose.yml
```

## 3. Backend Folder Structure
```text
backend/app/
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
```

## 4. Frontend Folder Structure
```text
frontend/
├── app/
├── components/
├── hooks/
├── contexts/
├── services/
├── types/
├── lib/
├── styles/
└── public/
```

## 5. Backend Module Design
### Authentication Service
- Verify Google OAuth tokens
- Create user accounts
- Generate JWT
- Validate sessions

Methods: `login()`, `verify_google_token()`, `generate_jwt()`, `get_current_user()`

### Workspace Service
Methods: `create_workspace()`, `update_workspace()`, `delete_workspace()`, `get_workspace()`

### Document Service
Methods: `upload_document()`, `delete_document()`, `get_document()`, `reindex_document()`

### Chat Service
Methods: `chat()`, `save_message()`, `get_history()`

### Search Service
Methods: `search()`, `retrieve()`, `rerank()`, `build_context()`

### Connector Service
Methods: `connect()`, `sync()`, `disconnect()`, `parse()`

## 6. Repository Layer
Repositories:
- UserRepository
- WorkspaceRepository
- DocumentRepository
- ConversationRepository
- ConnectorRepository

## 7. Database Models
- User
- Workspace
- Document
- Chunk
- Conversation
- Message
- Connector

Relationship: User → Workspace → Document → Chunk

## 8. Schema Layer
- UserCreate
- UserResponse
- WorkspaceCreate
- DocumentUpload
- ChatRequest
- ChatResponse

## 9. Connector Framework
BaseConnector with implementations:
- PDFConnector
- GitHubConnector
- GoogleDriveConnector
- NotionConnector

Interface: `connect()`, `sync()`, `parse()`, `index()`

## 10. Retrieval Engine
Pipeline:
Query Rewriter → Embedding Generator → Hybrid Retriever → Metadata Filter → Cross-Encoder Reranker → Context Builder

## 11. Embedding Module
Model: **BGE-M3**

Methods:
- `embed_document()`
- `embed_query()`

## 12. Reranker Module
Model: **BAAI BGE-Reranker**

Method:
- `rerank()`

## 13. LLM Provider Layer
Interface: `BaseLLMProvider.generate()`

Implementations:
- GeminiProvider
- OpenRouterProvider

## 14. API Layer
- /auth
- /workspaces
- /upload
- /search
- /chat
- /connectors

Flow:
API → Service → Repository → Database

## 15. Middleware
- JWT Authentication
- Request Logging
- Global Exception Handler
- Rate Limiting

## 16. Background Workers
- Document Parsing
- Chunk Generation
- Embedding Generation
- GitHub Sync
- Google Drive Sync
- Scheduled Re-indexing (Future)

## 17. Frontend Components
Pages:
- Login
- Dashboard
- Chat
- Upload
- Documents
- Connectors
- Settings

Shared:
- Navbar
- Sidebar
- Chat Window
- Upload Card
- Search Bar
- Citation Card
- Loader

## 18. React Hooks
- useAuth()
- useChat()
- useDocuments()
- useWorkspace()
- useSearch()

## 19. State Management
Global:
- Authentication
- Workspace
- Theme
- User

Server:
- React Query

## 20. Configuration
- DATABASE_URL
- GOOGLE_CLIENT_ID
- GOOGLE_CLIENT_SECRET
- JWT_SECRET
- QDRANT_URL
- QDRANT_API_KEY
- GEMINI_API_KEY
- OPENROUTER_API_KEY
- REDIS_URL

## 21. Error Handling
- Authentication: 400, 401, 403
- File: 413, 415
- Search: 500, 503
- LLM: 429, 500

## 22. Logging Strategy
Levels: INFO, WARNING, ERROR, CRITICAL

## 23. Security Design
- Google OAuth
- JWT Authorization
- Workspace Isolation
- Environment Variables
- File Validation
- HTTPS
- Rate Limiting

## 24. Design Patterns
- Repository Pattern
- Service Layer
- Dependency Injection
- Factory Pattern
- Strategy Pattern
- Adapter Pattern
- Singleton

## 25. Coding Standards
Backend:
- Python 3.12+
- PEP8
- Type Hints
- Async Endpoints
- Black
- Ruff

Frontend:
- TypeScript
- ESLint
- Prettier
- Functional Components
- React Hooks

## 26. Testing Strategy
Backend:
- Unit
- Integration
- API Tests

Frontend:
- Component
- UI Tests

End-to-End:
- Authentication
- Upload
- Chat
- Search

## 27. Future Extensibility
- Slack, Jira, Confluence Connectors
- Claude, GPT, Llama
- S3, Azure Blob
- Kubernetes
- Prometheus, Grafana, Langfuse

## 28. Development Sequence
1. Authentication, Workspace, Database
2. Upload, Parsing, Chunking
3. Embeddings, Qdrant, Search
4. Chat, Gemini Integration
5. GitHub Connector
6. Google Drive Connector
7. Deployment
