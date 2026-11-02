# Lumora API Integration Guide (backend v1)

Generated from the running application's OpenAPI schema and router code. Endpoint tables, field names, types and constraints below are taken from the actual Pydantic models; nothing is hand-invented. Re-generate after changing a route or schema.

## Conventions

- **Base URL:** `http://localhost:8000` in development (`PORT` setting). All feature routes are under `/api/v1`. `GET /` and `GET /health` are unversioned.
- **Authentication:** every route except `GET /`, `GET /health` and `POST /api/v1/auth/google` requires `Authorization: Bearer <access_token>`. Missing, malformed, expired, wrong-type or unknown-user tokens all return `401` with code `UNAUTHORIZED`.
- **Success responses are bare JSON objects/arrays** (no envelope). **Errors use an envelope:**
```json
{ "success": false, "error": { "code": "DOCUMENT_NOT_FOUND", "message": "..." } }
```
- **Validation errors** (`422`, code `VALIDATION_ERROR`) carry the fixed message `Invalid request` - there is no per-field detail, so the frontend must validate inputs itself (constraints are listed per schema below).
- **Unexpected errors** return `500` / `INTERNAL_SERVER_ERROR` with a generic message; details are only in server logs.
- **Ownership:** resources belonging to another user are indistinguishable from missing ones - they return `404`, never `403`.
- **CORS:** allowed origins come from the `CORS_ORIGINS` setting (default `http://localhost:3000`). Allowed methods: GET, POST, PATCH, DELETE, OPTIONS; allowed headers: `Authorization`, `Content-Type`. Credentials/cookies are not used.
- **Health:** `GET /health` returns `{status, environment, app_name}`. It does not check the database or Qdrant.
- **Document indexing is a separate step:** `POST /api/v1/documents/upload` only stores the file (`status: "Uploaded"`, `chunk_count: 0`). Call `POST /api/v1/documents/{document_id}/reindex` to parse, chunk, embed and index it (`status` becomes `"Indexed"`, or `"Failed"` with a `422 INGESTION_FAILED`). Search and chat only see indexed documents.
- **Connector tokens** (GitHub token, Google Drive access token) are sent in request bodies, used for that request only, and never stored or returned. Google Drive tokens are obtained outside this API (no OAuth callback flow exists yet).

## Endpoints

| Method | Path | Auth | Success | Request body / params | Response |
|---|---|---|---|---|---|
| GET | `/` | none | 200 |  |  |
| POST | `/api/v1/auth/google` | none | 200 | GoogleAuthRequest | GoogleAuthResponse |
| POST | `/api/v1/auth/logout` | Bearer | 200 |  | LogoutResponse |
| GET | `/api/v1/auth/me` | Bearer | 200 |  | UserResponse |
| POST | `/api/v1/chat` | Bearer | 200 | ChatRequest | ChatResponse |
| GET | `/api/v1/chat/history` | Bearer | 200 |  | ConversationResponse[] |
| GET | `/api/v1/chat/{conversation_id}` | Bearer | 200 | `conversation_id` (path, required) | ConversationHistoryResponse |
| DELETE | `/api/v1/chat/{conversation_id}` | Bearer | 204 | `conversation_id` (path, required) |  |
| GET | `/api/v1/connectors` | Bearer | 200 | `workspace_id` (query, required) | ConnectorResponse[] |
| POST | `/api/v1/connectors/github` | Bearer | 201 | GitHubConnectorCreate | ConnectorResponse |
| POST | `/api/v1/connectors/google-drive` | Bearer | 201 | GoogleDriveConnectorCreate | ConnectorResponse |
| DELETE | `/api/v1/connectors/{connector_id}` | Bearer | 204 | `connector_id` (path, required) |  |
| POST | `/api/v1/connectors/{connector_id}/sync` | Bearer | 200 | GitHubSyncRequest; `connector_id` (path, required) | GitHubSyncResponse |
| POST | `/api/v1/connectors/{connector_id}/sync/google-drive` | Bearer | 200 | GoogleDriveSyncRequest; `connector_id` (path, required) | GoogleDriveSyncResponse |
| GET | `/api/v1/documents` | Bearer | 200 | `workspace_id` (query, required) | DocumentResponse[] |
| POST | `/api/v1/documents/upload` | Bearer | 201 | multipart: Body_upload_document_api_v1_documents_upload_post | DocumentResponse |
| GET | `/api/v1/documents/{document_id}` | Bearer | 200 | `document_id` (path, required) | DocumentResponse |
| DELETE | `/api/v1/documents/{document_id}` | Bearer | 200 | `document_id` (path, required) | object |
| POST | `/api/v1/documents/{document_id}/reindex` | Bearer | 200 | `document_id` (path, required) | DocumentResponse |
| POST | `/api/v1/search` | Bearer | 200 | SearchRequest | SearchResponse |
| GET | `/api/v1/workspaces` | Bearer | 200 |  | WorkspaceResponse[] |
| POST | `/api/v1/workspaces` | Bearer | 201 | WorkspaceCreate | WorkspaceResponse |
| PATCH | `/api/v1/workspaces/{workspace_id}` | Bearer | 200 | WorkspaceUpdate; `workspace_id` (path, required) | WorkspaceResponse |
| DELETE | `/api/v1/workspaces/{workspace_id}` | Bearer | 200 | `workspace_id` (path, required) | object |
| GET | `/health` | none | 200 |  |  |

Notes on specific responses:

- `DELETE /api/v1/documents/{document_id}` and `DELETE /api/v1/workspaces/{workspace_id}` return `200` with a JSON object containing a `message` string. `DELETE` on a conversation or connector returns `204` with no body.
- `POST /api/v1/documents/upload` is `multipart/form-data` with fields `workspace_id` (UUID) and `file` (binary). Supported types: `pdf`, `docx`, `txt`, `md`; the size limit is `MAX_DOCUMENT_SIZE_MB` (default 20) and exceeding it returns `413 FILE_TOO_LARGE`.
- Deleting a workspace also removes its documents, chunks, connectors, stored files and vectors.
- Google Drive and GitHub sync responses report per-run counts (`files_added`, `files_updated`, `files_deleted`, `files_unchanged`, `files_skipped`; Drive additionally `files_failed` and `notes`).

## Schemas

### GoogleAuthRequest

| Field | Type | Required | Constraints |
|---|---|---|---|
| `google_token` | string | yes |  |

### GoogleAuthResponse

| Field | Type | Required | Constraints |
|---|---|---|---|
| `access_token` | string | yes |  |
| `user` | AuthUserSummary | yes |  |

### AuthUserSummary

| Field | Type | Required | Constraints |
|---|---|---|---|
| `id` | string (uuid) | yes |  |
| `name` | string | yes |  |
| `email` | string | yes |  |

### LogoutResponse

| Field | Type | Required | Constraints |
|---|---|---|---|
| `message` | string | no | default='Successfully logged out' |

### UserResponse

| Field | Type | Required | Constraints |
|---|---|---|---|
| `id` | string (uuid) | yes |  |
| `email` | string | yes |  |
| `name` | string | yes |  |
| `picture_url` | string | null | yes |  |
| `created_at` | string (date-time) | yes |  |
| `updated_at` | string (date-time) | yes |  |

### ChatRequest

| Field | Type | Required | Constraints |
|---|---|---|---|
| `query` | string | yes |  |
| `workspace_id` | string (uuid) | yes |  |
| `conversation_id` | string (uuid) | null | no |  |
| `document_id` | string (uuid) | null | no |  |
| `top_k` | integer | no | minimum=1.0, maximum=50.0, default=5 |

### ChatResponse

| Field | Type | Required | Constraints |
|---|---|---|---|
| `answer` | string | yes |  |
| `query` | string | yes |  |
| `conversation_id` | string (uuid) | yes |  |
| `sources` | SearchSourceResponse[] | no |  |

### SearchSourceResponse

| Field | Type | Required | Constraints |
|---|---|---|---|
| `chunk_id` | string (uuid) | yes |  |
| `document_id` | string (uuid) | yes |  |
| `filename` | string | yes |  |
| `source` | string | yes |  |
| `chunk_index` | integer | yes |  |
| `score` | number | yes |  |
| `content` | string | null | no |  |

### ConversationResponse

| Field | Type | Required | Constraints |
|---|---|---|---|
| `id` | string (uuid) | yes |  |
| `title` | string | null | no |  |
| `created_at` | string (date-time) | yes |  |

### ConversationHistoryResponse

| Field | Type | Required | Constraints |
|---|---|---|---|
| `id` | string (uuid) | yes |  |
| `title` | string | null | no |  |
| `created_at` | string (date-time) | yes |  |
| `messages` | MessageResponse[] | no |  |

### MessageResponse

| Field | Type | Required | Constraints |
|---|---|---|---|
| `id` | string (uuid) | yes |  |
| `role` | string | yes |  |
| `content` | string | yes |  |
| `created_at` | string (date-time) | yes |  |

### ConnectorResponse

| Field | Type | Required | Constraints |
|---|---|---|---|
| `id` | string (uuid) | yes |  |
| `workspace_id` | string (uuid) | yes |  |
| `type` | string | yes |  |
| `connection_name` | string | yes |  |
| `github_repo` | string | null | no |  |
| `drive_account_email` | string | null | no |  |
| `drive_root_folder_id` | string | null | no |  |
| `last_synced` | string (date-time) | null | no |  |
| `active` | boolean | yes |  |

### GitHubConnectorCreate

| Field | Type | Required | Constraints |
|---|---|---|---|
| `workspace_id` | string (uuid) | yes |  |
| `repo_full_name` | string | yes |  |
| `github_token` | string | yes |  |
| `connection_name` | string | null | no |  |

### GoogleDriveConnectorCreate

| Field | Type | Required | Constraints |
|---|---|---|---|
| `workspace_id` | string (uuid) | yes |  |
| `access_token` | string | yes |  |
| `root_folder_id` | string | null | no | pattern=^[A-Za-z0-9_-]{1,128}$ |
| `connection_name` | string | null | no |  |

### GitHubSyncRequest

| Field | Type | Required | Constraints |
|---|---|---|---|
| `github_token` | string | yes |  |

### GitHubSyncResponse

| Field | Type | Required | Constraints |
|---|---|---|---|
| `connector_id` | string (uuid) | yes |  |
| `repository` | string | yes |  |
| `files_discovered` | integer | yes |  |
| `files_added` | integer | yes |  |
| `files_updated` | integer | yes |  |
| `files_deleted` | integer | yes |  |
| `files_unchanged` | integer | yes |  |
| `files_skipped` | integer | yes |  |
| `status` | string | yes |  |

### GoogleDriveSyncRequest

| Field | Type | Required | Constraints |
|---|---|---|---|
| `access_token` | string | yes |  |

### GoogleDriveSyncResponse

| Field | Type | Required | Constraints |
|---|---|---|---|
| `connector_id` | string (uuid) | yes |  |
| `files_discovered` | integer | yes |  |
| `files_added` | integer | yes |  |
| `files_updated` | integer | yes |  |
| `files_deleted` | integer | yes |  |
| `files_unchanged` | integer | yes |  |
| `files_skipped` | integer | yes |  |
| `files_failed` | integer | yes |  |
| `status` | string | yes |  |
| `notes` | string[] | no |  |

### DocumentResponse

| Field | Type | Required | Constraints |
|---|---|---|---|
| `id` | string (uuid) | yes |  |
| `workspace_id` | string (uuid) | yes |  |
| `filename` | string | yes |  |
| `file_type` | string | yes |  |
| `file_size` | integer | yes |  |
| `status` | DocumentStatus | yes |  |
| `chunk_count` | integer | yes |  |
| `uploaded_at` | string (date-time) | yes |  |

### DocumentStatus

| Field | Type | Required | Constraints |
|---|---|---|---|

### Body_upload_document_api_v1_documents_upload_post

| Field | Type | Required | Constraints |
|---|---|---|---|
| `workspace_id` | string (uuid) | yes |  |
| `file` | string | yes |  |

### SearchRequest

| Field | Type | Required | Constraints |
|---|---|---|---|
| `query` | string | yes |  |
| `workspace_id` | string (uuid) | yes |  |
| `document_id` | string (uuid) | null | no |  |
| `top_k` | integer | no | minimum=1.0, maximum=50.0, default=5 |

### SearchResponse

| Field | Type | Required | Constraints |
|---|---|---|---|
| `query` | string | yes |  |
| `context` | string | yes |  |
| `sources` | SearchSourceResponse[] | no |  |

### WorkspaceResponse

| Field | Type | Required | Constraints |
|---|---|---|---|
| `id` | string (uuid) | yes |  |
| `user_id` | string (uuid) | yes |  |
| `name` | string | yes |  |
| `created_at` | string (date-time) | yes |  |

### WorkspaceCreate

| Field | Type | Required | Constraints |
|---|---|---|---|
| `name` | string | yes | minLength=1, maxLength=100 |

### WorkspaceUpdate

| Field | Type | Required | Constraints |
|---|---|---|---|
| `name` | string | null | no | minLength=1, maxLength=100 |

## Error codes

| Code | HTTP status |
|---|---|
| `CONNECTOR_MISSING_REPOSITORY` | 400 |
| `CONNECTOR_NOT_FOUND` | 404 |
| `CONVERSATION_NOT_FOUND` | 404 |
| `DOCUMENT_NOT_FOUND` | 404 |
| `FILE_TOO_LARGE` | 413 |
| `GITHUB_REPOSITORY_NOT_FOUND` | 404 |
| `GOOGLE_DRIVE_RESOURCE_NOT_FOUND` | 404 |
| `INGESTION_FAILED` | 422 |
| `INTERNAL_SERVER_ERROR` | 500 |
| `INVALID_CHAT_REQUEST` | 400 |
| `INVALID_GITHUB_CREDENTIALS` | 400 |
| `INVALID_GOOGLE_DRIVE_CREDENTIALS` | 400 |
| `INVALID_GOOGLE_TOKEN` | 401 |
| `INVALID_SEARCH_REQUEST` | 400 |
| `LLM_GENERATION_FAILED` | 500 |
| `TOO_MANY_REQUESTS` | 429 |
| `UNAUTHORIZED` | 401 |
| `UNSUPPORTED_CONNECTOR_TYPE` | 400 |
| `UNSUPPORTED_FILE_TYPE` | 415 |
| `VALIDATION_ERROR` | 422 |
| `WORKSPACE_NOT_FOUND` | 404 |

## Required environment variables

See `.env.example` at the repository root. Required: `SECRET_KEY`, `GOOGLE_CLIENT_ID`. Needed for full functionality: `DATABASE_URL`, `QDRANT_URL` (+ `QDRANT_API_KEY` if secured), `GEMINI_API_KEY` (chat only). In `ENVIRONMENT=production` the app refuses to start without `DATABASE_URL` and a `SECRET_KEY` of at least 32 characters.
