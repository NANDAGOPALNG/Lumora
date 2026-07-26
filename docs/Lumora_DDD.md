Lumora
Database Design Document (DDD)
Version: 1.0
Author: Nanda Gopal D
Database: PostgreSQL + Qdrant

Table of Contents
Introduction
Database Architecture
Database Selection
Entity Relationship Diagram
Relational Database Schema
Vector Database Schema
Table Definitions
Relationships
Constraints
Indexing Strategy
UUID Strategy
Transactions
Scalability
Backup & Recovery
Future Database Enhancements

1. Introduction
This document describes the logical and physical database design of Lumora.
Lumora uses two databases:
PostgreSQL (Relational Database)
Qdrant (Vector Database)
The relational database stores structured application data, while Qdrant stores vector embeddings used for semantic retrieval.
This hybrid architecture provides efficient transactional storage and high-performance vector search.

2. Database Architecture
                    Lumora

                         │

        ┌────────────────┴────────────────┐

        │                                 │

 PostgreSQL                       Qdrant Vector DB

        │                                 │

 Users                           Document Embeddings

 Workspaces                      Chunk Embeddings

 Documents                       Metadata

 Conversations                   Vector Index

 Messages

 Connectors

3. Why PostgreSQL?
PostgreSQL is selected because Lumora contains highly relational data.
Examples:
Users own Workspaces
Workspaces own Documents
Users own Conversations
Documents generate Chunks
These relationships are efficiently managed using foreign keys and ACID transactions.
Advantages:
ACID compliant
Mature ecosystem
Excellent indexing
Supports JSONB
Free tier (Neon)

4. Why Qdrant?
Qdrant stores semantic vectors.
Advantages
Fast vector search
Metadata filtering
Production ready
Open-source
Python SDK
Cloud free tier












5. Entity Relationship Diagram


6. Database Tables
KnowledgeOS Version 1 contains seven relational tables.

7. Table Definitions

users
Purpose
Stores authenticated users.

workspaces
Purpose
Logical isolation of user data.

documents
Purpose
Stores uploaded document metadata.
Status values
Uploaded
Processing
Indexed
Failed

chunks
Purpose
Represents semantic chunks.

conversations
Purpose
Stores chat sessions.

messages
Purpose
Stores chat messages.

connectors
Purpose
Stores connected external sources.
Supported Types
GitHub
Google Drive
Notion

8. Qdrant Collection Design
Collection Name
knowledge_chunks
Payload
{
  "chunk_id": "uuid",
  "document_id": "uuid",
  "workspace_id": "uuid",
  "filename": "guide.pdf",
  "chunk_index": 5,
  "source": "pdf",
  "created_at": "2026-01-10T12:00:00Z"
}
Vector
BGE-M3

Dimension: 1024

9. Relationships
User

↓

Workspace

↓

Document

↓

Chunk

↓

Embedding (Qdrant)

Conversation Relationship
User

↓

Conversation

↓

Messages

10. Constraints
Primary Keys
All tables use UUID.
Foreign Keys
workspace.user_id

↓

users.id
document.workspace_id

↓

workspace.id
chunk.document_id

↓

documents.id
conversation.user_id

↓

users.id
message.conversation_id

↓

conversation.id

11. Indexing Strategy
Indexes
users.email
Unique
documents.workspace_id
chunks.document_id
messages.conversation_id
GIN Index
chunks.metadata

12. UUID Strategy
All entities use UUID v4.
Reasons
Globally unique
Better for distributed systems
Harder to guess
SaaS friendly

13. Transactions
Transactions are used for
Document Upload
Insert Document

↓

Insert Chunks

↓

Insert Metadata

↓

Commit
If embedding generation fails
Rollback

14. Database Security
Foreign Key Constraints
Cascade Delete
Parameterized Queries
Workspace Isolation
Connection Pooling
SSL Enabled

15. Backup Strategy
PostgreSQL
Daily backups (Neon managed)
Qdrant
Snapshot exports

16. Future Enhancements
Future tables
organizations
organization_members
api_keys
audit_logs
usage_metrics
notifications
evaluations
prompts

17. Database Optimization
PostgreSQL
Connection Pooling
Prepared Statements
JSONB Metadata
Composite Indexes
Qdrant
Payload Filtering
HNSW Index
Vector Compression

18. Database Naming Convention
Tables
snake_case
Columns
snake_case
Primary Keys
id
Foreign Keys
user_id

workspace_id

document_id
Timestamps
created_at

updated_at

19. Database Access Pattern
Frontend

↓

FastAPI

↓

Service Layer

↓

Repository Layer

↓

PostgreSQL

↓

Qdrant

20. Summary
KnowledgeOS adopts a hybrid database architecture:
PostgreSQL manages relational data such as users, workspaces, documents, conversations, and connectors.
Qdrant stores vector embeddings for semantic retrieval.
This design separates transactional workloads from vector search, making the system easier to maintain and scale.

Two improvements I recommend
I would make two additions beyond what's in most database design documents:





1. Data Lifecycle Diagram
This shows how information flows through the system:


2. Database Access Sequence Diagram
