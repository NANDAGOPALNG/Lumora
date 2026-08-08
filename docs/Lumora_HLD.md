Proposed HLD Structure

## 1. Document Information

Project Name: Lumora 

Version: 1.0

Author: Nanda Gopal 



## 2. Purpose


KnowledgeOS is an AI-powered knowledge management platform designed to help users organize, search, and interact with information from multiple data sources through natural language. Instead of manually browsing documents or repositories, users can ask questions conversationally and receive context-aware, source-grounded responses.

The platform supports document ingestion from various sources, including PDF files and GitHub repositories, with an extensible architecture that allows additional connectors to be integrated in the future. Uploaded content is processed through an ingestion pipeline that extracts text, generates semantic embeddings, and indexes the information for efficient retrieval.

When a user submits a query, KnowledgeOS employs a Retrieval-Augmented Generation (RAG) pipeline that combines semantic search, keyword search, metadata filtering, and reranking to identify the most relevant content. The retrieved context is then provided to a Large Language Model (LLM) to generate accurate, contextual, and explainable responses while maintaining references to the original source material.

The primary objectives of KnowledgeOS are to:

- Provide a unified interface for accessing knowledge from multiple sources.
- Enable fast and accurate semantic search across large document collections.
- Generate reliable, context-aware answers using Retrieval-Augmented Generation (RAG).
- Maintain source attribution to improve transparency and reduce hallucinations.
- Offer a modular architecture that supports new connectors, embedding models, retrieval strategies, and LLM providers with minimal changes.
- Deliver a scalable and secure platform suitable for both individual users and collaborative workspaces.

KnowledgeOS is designed with extensibility, maintainability, and production readiness in mind, making it suitable for personal knowledge management, technical documentation, enterprise knowledge bases, and AI-powered document assistants.



## 3. High-Level Architecture

![High Level Architecture](https://github.com/NANDAGOPALNG/Lumora/blob/main/docs/diagrams/Overall%20System%20Architecture.drawio.png)



## 4. Component Overview

Each component gets a dedicated section:

- Frontend 

- Backend 

- Authentication 

- PostgreSQL 

- Qdrant 

- Embedding Engine 

- Retrieval Engine 

- Reranker 

- LLM Provider 

- Connectors 

For each one we'll describe:

- Responsibilities 

- Inputs 

- Outputs 

- Dependencies 



## 5. Request Lifecycle


This section describes the end-to-end flow of a user query through the KnowledgeOS platform. The example below demonstrates how the system processes the query:

> **"How does authentication work?"**

The request lifecycle consists of the following stages:

### Step 1: User Submits a Query

The user enters a natural language question in the chat interface and submits it through the web application.

**Component:** Next.js Frontend

---

### Step 2: API Request

The frontend sends the query along with the authenticated user's JWT token, workspace identifier, and conversation context to the FastAPI backend.

The backend validates:

- User authentication
- Workspace access permissions
- Request payload

**Component:** Authentication Service

---

### Step 3: Query Preprocessing

The backend prepares the query before retrieval by:

- Cleaning and normalizing the input
- Rewriting ambiguous queries (if required)
- Generating an embedding using the configured embedding model

This embedding captures the semantic meaning of the user's question.

---

### Step 4: Hybrid Retrieval

The Retrieval Engine searches the indexed knowledge base using a hybrid retrieval strategy.

The retrieval process includes:

- Dense vector search against Qdrant
- Keyword/BM25 search
- Metadata filtering (workspace, document, connector, etc.)

The results from both retrieval methods are merged into a single candidate list.

---

### Step 5: Result Reranking

The candidate documents are passed through a Cross-Encoder reranker.

The reranker evaluates how relevant each retrieved chunk is to the user's question and sorts them by relevance score.

Only the highest-ranking chunks are selected for response generation.

---

### Step 6: Context Construction

The selected document chunks are combined into a structured context.

Additional information may include:

- Document title
- Source connector
- Page number or file path
- Metadata
- Conversation history

This ensures the language model receives only the most relevant information.

---

### Step 7: Response Generation

The constructed context and the user's question are sent to the configured Large Language Model (LLM).

The LLM generates a grounded response based solely on the retrieved context rather than relying on its pretrained knowledge.

This approach significantly reduces hallucinations and improves response accuracy.

---

### Step 8: Citation Generation

The system associates each generated answer with its originating document chunks.

This enables users to:

- Verify the information
- Navigate back to the original source
- Build trust in generated responses

---

### Step 9: Return Response

The backend returns the generated answer and supporting citations to the frontend.

The frontend displays:

- AI-generated response
- Source citations
- Referenced documents
- Conversation history

The interaction is then stored for future context within the workspace.

---

### Request Flow Summary

1. User submits a question.
2. Frontend sends the request to the backend.
3. Authentication and authorization are validated.
4. Query embedding is generated.
5. Hybrid retrieval searches relevant documents.
6. Retrieved results are reranked.
7. Relevant context is assembled.
8. Gemini 2.5 Flash generates a grounded response.
9. Citations are attached.
10. The response is returned to the user and stored in the conversation history.


## 6. Document Ingestion Flow

![High Level Architecture](https://github.com/NANDAGOPALNG/Lumora/blob/main/docs/diagrams/Document%20Ingestion%20Flow.drawio.png)


## 7. Retrieval Pipeline

One of the most important sections.

![High Level Architecture](https://github.com/NANDAGOPALNG/Lumora/blob/main/docs/diagrams/RAG%20Pipeline.drawio.png)



## 8. Connector Architecture

Instead of hardcoding connectors, we'll use a common interface:

BaseConnector



│



├── PDFConnector



├── GitHubConnector



├── GoogleDriveConnector



└── NotionConnector

This makes it easy to add more sources later.



## 9. Database Architecture

We'll explain why we use two storage systems:

PostgreSQL

Stores:

- Users 

- Workspaces 

- Documents 

- Conversations 

- Connectors 

- Metadata 

- Qdrant

Stores:

- Embeddings 

- Chunk metadata 

- Vector indexes 


![High Level Architecture](https://github.com/NANDAGOPALNG/Lumora/blob/main/docs/diagrams/Database%20Architecture.drawio.png)



## 10. Authentication Flow

![High Level Architecture](https://github.com/NANDAGOPALNG/Lumora/blob/main/docs/diagrams/Authentication%20Flow.drawio.png)



## 11. Deployment Architecture

We'll document the free-tier deployment:

![High Level Architecture](https://github.com/NANDAGOPALNG/Lumora/blob/main/docs/diagrams/Deployment%20Architecture.drawio.png)



## 12. Backend Component Architecture

![High Level Architecture](https://github.com/NANDAGOPALNG/Lumora/blob/main/docs/diagrams/Backend%20Component%20Architecture.drawio.png)


## 13. LLM Provider Abstraction

![High Level Architecture](https://github.com/NANDAGOPALNG/Lumora/blob/main/docs/diagrams/LLM%20Provider%20Abstraction.drawio.png)



## 14. Technology Decisions

This section explains the rationale behind the major technology choices made for KnowledgeOS. Each component was selected based on factors such as performance, scalability, maintainability, developer productivity, and suitability for AI-powered applications.

| Component | Selected Technology | Justification |
|-----------|---------------------|---------------|
| **Frontend** | Next.js | Provides a modern React framework with server-side rendering, optimized routing, excellent developer experience, and seamless deployment on Vercel. |
| **Backend** | FastAPI | High-performance Python web framework with asynchronous request handling, automatic OpenAPI documentation, and strong integration with AI/ML libraries. |
| **Database** | PostgreSQL | Reliable relational database used for storing users, workspaces, conversations, documents, connector configurations, and application metadata while ensuring ACID compliance. |
| **Vector Database** | Qdrant | Purpose-built vector database that offers efficient semantic search, metadata filtering, and high-performance similarity retrieval for Retrieval-Augmented Generation (RAG). |
| **Authentication** | Google OAuth + JWT | Google OAuth simplifies user onboarding by eliminating password management, while JWT enables secure, stateless authentication for API requests. |
| **Embeddings** | BGE-M3 | High-quality multilingual embedding model capable of generating semantic vector representations that improve retrieval accuracy across diverse document types. |
| **Large Language Model** | Gemini 2.5 Flash | Provides strong reasoning capabilities, fast response times, and cost-effective inference suitable for production-ready AI applications. |
| **Caching** | Upstash Redis | Stores frequently accessed data such as session information and cached responses, reducing latency and improving overall application performance. |
| **Deployment** | Vercel + Render | Separates frontend and backend deployments using managed cloud platforms, enabling simplified CI/CD, automatic scaling, and cost-effective hosting for public deployments. |

### Design Principles

The selected technologies follow these architectural principles:

- **Modularity:** Components can be replaced or upgraded with minimal changes to the overall system.
- **Scalability:** The architecture supports increasing workloads through horizontal scaling and distributed services.
- **Maintainability:** Well-supported frameworks and standardized interfaces simplify development and long-term maintenance.
- **Performance:** Asynchronous APIs, vector search, and caching minimize response latency.
- **Extensibility:** New connectors, embedding models, retrieval strategies, and LLM providers can be integrated without significant architectural changes.



## 15. Scalability

KnowledgeOS is designed with a modular and extensible architecture that supports future growth without requiring major architectural changes. As user adoption and feature requirements increase, the platform can be scaled both functionally and operationally.

### Future Scalability Areas

- **More Connectors:** Add support for additional data sources such as Slack, Jira, Confluence, SharePoint, and Google Drive by implementing the common connector interface.

- **More LLM Providers:** Integrate multiple LLM providers (e.g., OpenAI, Anthropic, OpenRouter, or self-hosted models) through the provider abstraction layer, enabling flexible model selection and failover.

- **Background Workers:** Offload resource-intensive tasks such as document ingestion, embedding generation, indexing, and connector synchronization to asynchronous background workers, improving system responsiveness.

- **Team Workspaces:** Extend the platform to support collaborative workspaces with role-based access control, shared knowledge bases, and multi-user conversations.

- **Multi-tenancy:** Support multiple organizations within a single deployment while ensuring complete isolation of data, authentication, and configuration for each tenant.

- **Horizontal API Scaling:** Deploy multiple instances of the FastAPI backend behind a load balancer to handle increased traffic and improve availability. Stateless services, shared databases, and distributed caching enable efficient horizontal scaling.



## 16. Security

- Google OAuth 

- JWT 

- HTTPS 

- Environment variables 

- Workspace isolation 

- File validation 

- Rate limiting 



## 17. Future Enhancements

- Slack Connector 

- Jira Connector 

- Confluence Connector 

- MCP Integration 

- LangGraph Agentic Workflows 

- Multi-agent Retrieval 

- Usage Analytics 

Evaluation Dashboard 

