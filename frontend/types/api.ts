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
