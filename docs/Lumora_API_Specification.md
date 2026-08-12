# Lumora API Specification

## Table of Contents
1. Introduction
2. Authentication
3. Base URL
4. Authentication Method
5. Error Response Format
6. Authentication APIs
7. Workspace APIs
8. Document APIs
9. Chat APIs
10. Search APIs
11. Connector APIs
12. Health APIs
13. Response Models
14. Status Codes
15. Rate Limits
16. API Versioning

## Introduction
Defines the REST APIs for KnowledgeOS.

## Base URL
`/api/v1`

## Authentication Method
Google OAuth with JWT Bearer tokens.

## Error Response Format
```json
{"success":false,"error":{"code":"ERROR_CODE","message":"Description"}}
```

## Authentication APIs
### POST /auth/google
Request:
```json
{"google_token":"..."}
```
Response:
```json
{"access_token":"...","user":{"id":"...","name":"...","email":"..."}}
```
Status: 200, 401, 500

### GET /auth/me
Returns current user.

### POST /auth/logout
Logs out current user.

## Workspace APIs
- GET /workspaces
- POST /workspaces
- PATCH /workspaces/{id}
- DELETE /workspaces/{id}

## Document APIs
- POST /documents/upload
- GET /documents
- GET /documents/{id}
- DELETE /documents/{id}
- POST /documents/{id}/reindex

## Chat APIs
- POST /chat
- GET /chat/history
- DELETE /chat/{id}

## Search APIs
- POST /search
- GET /search/suggestions

## Connector APIs
- POST /connectors/github
- POST /connectors/google-drive
- POST /connectors/notion
- GET /connectors
- DELETE /connectors/{id}

## Health APIs
- GET /health
- GET /metrics

## Response Models
Standard JSON response envelope.

## Status Codes
200, 201, 400, 401, 403, 404, 429, 500

## Rate Limits
Per-user and per-IP throttling.

## API Versioning
All endpoints use `/api/v1`.
