# Lumora Database Design Document (DDD)

## Table of Contents
1. Introduction
2. Database Architecture
3. Database Selection
4. Entity Relationship Diagram
5. Relational Database Schema
6. Vector Database Schema
7. Table Definitions
8. Relationships
9. Constraints
10. Indexing Strategy
11. UUID Strategy
12. Transactions
13. Database Security
14. Backup Strategy
15. Future Enhancements
16. Database Optimization
17. Naming Convention
18. Database Access Pattern
19. Summary

## 1. Introduction
Lumora uses a hybrid database architecture consisting of PostgreSQL for relational data and Qdrant for vector embeddings.

## 2. Database Architecture
- PostgreSQL: Users, Workspaces, Documents, Conversations, Messages, Connectors
- Qdrant: Document and chunk embeddings with vector indexes

## 3. Database Selection
### PostgreSQL
- ACID compliant
- Foreign keys
- JSONB support
- Neon free tier

### Qdrant
- Semantic vector search
- Metadata filtering
- Python SDK
- Cloud free tier

## 4. Entity Relationship Diagram

![Entity Relationship Diagram](https://github.com/NANDAGOPALNG/Lumora/blob/main/docs/diagrams/Entity%20Relationship%20Diagram.png)

## 5. Relational Database Schema
Tables:
- users
- workspaces
- documents
- chunks
- conversations
- messages
- connectors

## 6. Vector Database Schema
Collection: `knowledge_chunks`

Vector model: **BGE-M3** (1024 dimensions)

Payload:
```json
{"chunk_id":"uuid","document_id":"uuid","workspace_id":"uuid","filename":"guide.pdf","chunk_index":5,"source":"pdf"}
```

## 7. Table Definitions
### users
id,email,name,picture_url,created_at,updated_at

### workspaces
id,user_id,name,created_at

### documents
id,workspace_id,filename,file_type,file_size,storage_path,status,chunk_count,uploaded_at

Status: Uploaded, Processing, Indexed, Failed

### chunks
id,document_id,chunk_index,content,metadata

### conversations
id,user_id,title,created_at

### messages
id,conversation_id,role,content,created_at

### connectors
id,workspace_id,type,connection_name,last_synced,active

Supported: GitHub, Google Drive, Notion

## 8. Relationships
User → Workspace → Document → Chunk → Embedding

User → Conversation → Message

## 9. Constraints
- UUID primary keys
- Foreign key relationships
- Workspace isolation

## 10. Indexing Strategy
- users.email (unique)
- documents.workspace_id
- chunks.document_id
- messages.conversation_id
- GIN index on chunks.metadata

## 11. UUID Strategy
UUID v4 for all entities.

## 12. Transactions
Document upload transaction:
Insert document → Insert chunks → Insert metadata → Commit/Rollback.

## 13. Database Security
- Foreign keys
- Cascade delete
- Parameterized queries
- SSL
- Connection pooling

## 14. Backup Strategy
- PostgreSQL daily backups
- Qdrant snapshots

## 15. Future Enhancements
Organizations, API keys, audit logs, usage metrics, notifications, evaluations, prompts.

## 16. Database Optimization
PostgreSQL: Prepared statements, JSONB, composite indexes.
Qdrant: Payload filtering, HNSW, vector compression.

## 17. Naming Convention
snake_case tables and columns, UUID ids, *_id foreign keys.

## 18. Database Access Pattern
Frontend → FastAPI → Service Layer → Repository Layer → PostgreSQL → Qdrant

## 19. Summary
Hybrid architecture separates transactional storage from semantic retrieval for scalability and maintainability.

## 20 Two improvements 

### 1. Data Lifecycle Diagram

![Data Lifecycle Diagram](https://github.com/NANDAGOPALNG/Lumora/blob/main/docs/diagrams/Data%20Lifecycle%20Diagram.drawio.png)

### 2. Database Access Sequence Diagram

![Database Access Sequence Diagram](https://github.com/NANDAGOPALNG/Lumora/blob/main/docs/diagrams/Database%20Access%20Sequence%20Diagram.drawio.png)
