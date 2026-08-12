# Lumora Software Requirements Specification (SRS)

Lumora/

docs/

01_SRS.pdf

02_HLD.pdf

03_LLD.pdf

04_DatabaseDesign.pdf

05_API_Specification.pdf

06_DeploymentGuide.pdf

07_TestPlan.pdf

08_UserManual.pdf

This immediately makes the repository look far more professional.

Lumora

Software Requirements Specification (SRS)

Version 1.0

Document Information

Field

Value

Project Name

KnowledgeOS

Version

## 1.0

Document Type

Software Requirements Specification

Prepared By

Nanda Gopal D

Project Type

AI SaaS / Enterprise RAG Platform

Status

Draft

Language

Python, TypeScript

Table of Contents

Introduction

Project Overview

Objectives

Scope

Stakeholders

Functional Requirements

Non Functional Requirements

System Features

Technology Stack

External Integrations

Constraints

Assumptions

Future Scope

## 1. Introduction

Lumora is an AI-powered enterprise knowledge platform that enables users to search, retrieve, and interact with organizational knowledge using Retrieval-Augmented Generation (RAG).

Instead of searching multiple platforms individually, users can connect their knowledge sources and ask natural language questions. The platform retrieves relevant information, generates grounded responses using an LLM, and provides citations for every answer.

KnowledgeOS is designed as a modular, production-oriented SaaS application with extensible connectors and a scalable architecture.

## 2. Problem Statement

Organizations store information across multiple disconnected platforms such as:

GitHub

Google Drive

Notion

PDF documents

Internal documentation

Employees waste significant time searching for information because existing search systems are fragmented and primarily keyword-based.

KnowledgeOS addresses this challenge by creating a unified semantic search and conversational AI platform.

## 3. Project Objectives

The primary objectives of Lumora are:

Build a production-oriented RAG application.

Provide semantic search across multiple knowledge sources.

Generate grounded AI responses with citations.

Support extensible connectors for future integrations.

Deliver a deployable SaaS application suitable for real-world usage.

Demonstrate production engineering practices in AI systems.

## 4. Project Scope

In Scope (Version 1)

Authentication

Google OAuth Sign-In

JWT-based session management

User Workspace

Each user receives:

Personal workspace

Uploaded documents

Connected repositories

Chat history

Document Management

Supported document formats:

PDF

DOCX

TXT

Markdown

Users can:

Upload documents

View documents

Delete documents

Re-index documents

AI Chat

Users can:

Ask questions

Summarize documents

Compare documents

Search knowledge

Every response contains:

Grounded answer

Source citations

Confidence indicator

Referenced document metadata

Search

KnowledgeOS supports:

Semantic Search

Hybrid Search

Metadata Filtering

Conversation Context

Connectors

Version 1 includes:

PDF Connector

GitHub Repository Connector

Version 2:

Google Drive

Notion

## 5. Stakeholders

Primary User

Individual users

Students

Developers

Startup teams

System Administrator

Application owner

Future

Organizations

Teams

## 6. Functional Requirements

Authentication

The system shall:

Authenticate users using Google OAuth.

Generate JWT access tokens.

Store authenticated user profiles.

Maintain secure user sessions.

Workspace

The system shall:

Create a workspace for every new user.

Store uploaded knowledge separately for each workspace.

Prevent cross-workspace access.

Document Upload

The system shall:

Accept supported file formats.

Validate uploaded files.

Store document metadata.

Trigger background indexing.

Document Processing

The system shall:

Extract text

Clean text

Generate metadata

Chunk documents

Generate embeddings

Store vectors

Search

The system shall:

Accept natural language queries.

Retrieve relevant chunks.

Rank retrieved documents.

Send context to the LLM.

AI Response

The system shall:

Generate grounded responses.

Include citations.

Maintain conversation history.

Display confidence score.

GitHub Connector

The system shall:

Accept repository URLs.

Retrieve repository documentation.

Parse Markdown files.

Index repository knowledge.

Enable conversational search.

## 7. Non Functional Requirements

Performance

Query response under 5 seconds for typical workloads.

Efficient document indexing.

Asynchronous processing for long-running tasks.

Scalability

The architecture shall support:

Additional connectors

Additional LLM providers

Additional vector databases

Future multi-tenant organizations

Security

Google OAuth authentication

JWT authorization

Secure environment variables

Workspace isolation

HTTPS deployment

Reliability

Graceful API error handling

Retry mechanisms for connector failures

Logging for failed operations

Maintainability

The application shall follow:

Modular architecture

Service-oriented design

Repository pattern

Clear project structure

## 8. System Features

User Features

Google Login

Upload documents

Connect GitHub repository

AI Chat

Semantic Search

Document Management

Chat History

AI Features

Semantic Chunking

Dense Embeddings

Hybrid Retrieval

Cross-Encoder Reranking

Context Compression

Source Grounding

Citation Generation

Administration

User management

Workspace monitoring

Document statistics

Connector management

## 9. Technology Stack

Frontend

Next.js

TypeScript

Tailwind CSS

shadcn/ui

React Query

Backend

FastAPI

SQLAlchemy

Alembic

Pydantic

Authentication

Google OAuth

JWT

Database

PostgreSQL (Neon)

Reason:

Strong relational support

Reliable free tier

Well suited for users, workspaces, conversations, and metadata

Vector Database

Qdrant Cloud

Reason:

Production-grade vector search

Metadata filtering

Excellent Python SDK

Free tier suitable for portfolio deployment

Embedding Model

BAAI BGE-M3

Reason:

Open source

Strong retrieval performance

Supports hybrid retrieval

Reranker

BAAI BGE-Reranker

Large Language Model

Primary:

Gemini 2.5 Flash

Fallback:

OpenRouter-compatible provider

Reason:

Keeps the architecture provider-agnostic and avoids lock-in.

Cache

Upstash Redis

Deployment

Frontend:

Vercel

Backend:

Render

Database:

Neon PostgreSQL

Vector Database:

Qdrant Cloud

Cache:

Upstash Redis

## 10. External Integrations

Current

Google OAuth

Gemini API

GitHub API

Future

Google Drive API

Notion API

## 11. Constraints

Single-developer project.

Zero infrastructure budget.

Uses free-tier cloud services.

Designed for portfolio demonstration while following production engineering practices.

Cloud-hosted and publicly accessible.

## 12. Assumptions

Users possess a Google account.

Internet connectivity is available.

Free-tier service quotas are sufficient for demonstration workloads.

Repository sizes remain within practical limits for indexing.

## 13. Future Scope

Future versions may include:

Google Drive synchronization

Notion synchronization

Slack connector

Jira connector

Confluence connector

OCR support

Image understanding

Multi-tenant organizations

Team collaboration

AI Agents

MCP Server integration

LangGraph orchestration

Advanced analytics dashboard

Usage monitoring

Evaluation pipeline

Enterprise RBAC

Success Criteria

KnowledgeOS v1 will be considered successful if it:

Provides secure Google-based authentication.

Allows users to upload and manage documents.

Supports GitHub repository indexing.

Delivers grounded AI responses with citations.

Is deployed publicly using free-tier infrastructure.

Demonstrates modular architecture and production-oriented engineering suitable for technical interviews and portfolio review.

One final recommendation

I recommend treating this as a software product, not just a coding project. Create the documentation in the following order:

SRS (this document)

High-Level Design (HLD) – architecture, workflows, component interactions.

Low-Level Design (LLD) – classes, modules, folder structure, interfaces.

Database Design – ER diagrams, schemas, indexes.

API Specification – endpoints, request/response contracts.

Deployment Guide – infrastructure, environment variables, CI/CD.

Following this sequence mirrors how many engineering teams plan and document systems before implementation, and it gives you a repository that demonstrates both software engineering discipline and AI application development.

