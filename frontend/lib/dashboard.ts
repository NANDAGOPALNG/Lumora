import { FileUp, MessageSquare, RefreshCw, type LucideIcon } from "lucide-react";
import type { DashboardActivityType } from "@/types/api";

export const ACTIVITY_ICONS: Record<DashboardActivityType, LucideIcon> = {
  document_uploaded: FileUp,
  connector_synced: RefreshCw,
  conversation_created: MessageSquare,
};

export const ACTIVITY_LABELS: Record<DashboardActivityType, string> = {
  document_uploaded: "Document upload",
  connector_synced: "Connector sync",
  conversation_created: "Conversation",
};

/** Only app-relative paths are ever turned into links; anything else renders as plain text. */
export function safeInternalLink(link: string | null | undefined): string | null {
  if (!link || !link.startsWith("/") || link.startsWith("//") || link.includes("\\")) return null;
  return link;
}
