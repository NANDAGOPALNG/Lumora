/**
 * Backend contract types, transcribed from docs/API_Integration_Guide.md
 * (backend v1). Only the schemas needed by the first integration phases are
 * included; extend from the guide as features are built.
 */

export type Uuid = string;
export type IsoDateTime = string;

export interface ApiErrorEnvelope {
  success: false;
  error: { code: string; message: string };
}

export interface AuthUserSummary {
  id: Uuid;
  name: string;
  email: string;
}

export interface GoogleAuthRequest {
  google_token: string;
}

export interface GoogleAuthResponse {
  access_token: string;
  user: AuthUserSummary;
}

export interface UserResponse {
  id: Uuid;
  email: string;
  name: string;
  picture_url: string | null;
  created_at: IsoDateTime;
  updated_at: IsoDateTime;
}

export interface WorkspaceResponse {
  id: Uuid;
  user_id: Uuid;
  name: string;
  created_at: IsoDateTime;
}

export interface WorkspaceCreate {
  name: string; // 1-100 characters (trimmed by the backend)
}

export interface WorkspaceUpdate {
  name: string; // 1-100 characters (trimmed by the backend)
}

export interface MessageResponse {
  message: string;
}

export type DocumentStatus = "Uploaded" | "Processing" | "Indexed" | "Failed";

export interface DocumentResponse {
  id: Uuid;
  workspace_id: Uuid;
  filename: string;
  file_type: string;
  file_size: number;
  status: DocumentStatus;
  chunk_count: number;
  uploaded_at: IsoDateTime;
}

/** One retrieved chunk the answer drew on (SearchSourceResponse). */
export interface SearchSource {
  chunk_id: Uuid;
  document_id: Uuid;
  filename: string;
  /** The document's file type (e.g. "pdf"). */
  source: string;
  chunk_index: number;
  /** Cross-encoder relevance score; its scale isn't documented, so it is shown as-is. */
  score: number;
  content?: string | null;
}

export interface ChatRequest {
  query: string;
  workspace_id: Uuid;
  conversation_id?: Uuid;
  document_id?: Uuid;
  top_k?: number;
}

export interface ChatResponse {
  answer: string;
  /** The normalised query actually used for retrieval. */
  query: string;
  conversation_id: Uuid;
  sources: SearchSource[];
}

export interface ConversationSummary {
  id: Uuid;
  title: string | null;
  created_at: IsoDateTime;
}

export interface ChatMessage {
  id: Uuid;
  role: string; // "user" | "assistant"
  content: string;
  created_at: IsoDateTime;
}

export interface ConversationDetail {
  id: Uuid;
  title: string | null;
  created_at: IsoDateTime;
  messages: ChatMessage[];
}

export interface SearchRequest {
  query: string;
  workspace_id: Uuid;
  document_id?: Uuid;
  /** 1-50; the backend defaults to 5. */
  top_k?: number;
}

export interface SearchResponse {
  /** The normalised query actually used for retrieval. */
  query: string;
  /** The assembled context built from the results. It is not an independent result. */
  context: string;
  /** Retrieved passages, best first. */
  sources: SearchSource[];
}

/** Safe connector metadata; the backend never returns or stores a credential. */
export interface ConnectorResponse {
  id: Uuid;
  workspace_id: Uuid;
  type: string;
  connection_name: string;
  /** Canonical "owner/repo"; null for non-GitHub connectors and very old GitHub ones. */
  github_repo: string | null;
  drive_account_email: string | null;
  drive_root_folder_id: string | null;
  last_synced: IsoDateTime | null;
  active: boolean;
}

/** Request bodies carry the GitHub token. These types must never be used as cache keys or stored. */
export interface GitHubConnectorCreate {
  workspace_id: Uuid;
  repo_full_name: string;
  github_token: string;
  connection_name?: string;
}

export interface GitHubSyncRequest {
  github_token: string;
}

export interface GitHubSyncResponse {
  connector_id: Uuid;
  repository: string;
  files_discovered: number;
  files_added: number;
  files_updated: number;
  files_deleted: number;
  files_unchanged: number;
  files_skipped: number;
  /** Always "completed" today: the backend returns a finished summary, not live progress. */
  status: string;
}
