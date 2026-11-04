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
  name: string; // 1-100 characters
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
