import { CircleAlert, CircleCheck, CircleDashed } from "lucide-react";
import type { DocumentStatus } from "@/types/api";
import { Badge } from "@/components/ui/badge";
import { Spinner } from "@/components/ui/spinner";
import { cn } from "@/lib/utils";

const STYLES: Record<DocumentStatus, string> = {
  Uploaded: "bg-secondary text-secondary-foreground",
  Processing: "bg-brand-muted text-foreground",
  Indexed: "bg-secondary text-foreground",
  Failed: "bg-destructive/10 text-destructive",
};

interface DocumentStatusBadgeProps {
  status: DocumentStatus;
  /** True while this app has an index request in flight for the document. */
  indexing?: boolean;
}

export function DocumentStatusBadge({ status, indexing = false }: DocumentStatusBadgeProps) {
  const effective: DocumentStatus = indexing ? "Processing" : status;
  const label = indexing ? "Indexing" : status;

  return (
    <Badge data-status={effective} className={cn("gap-1.5 px-2 py-1", STYLES[effective])}>
      {effective === "Processing" && <Spinner className="size-3" aria-label={undefined} aria-hidden />}
      {effective === "Indexed" && <CircleCheck aria-hidden />}
      {effective === "Failed" && <CircleAlert aria-hidden />}
      {effective === "Uploaded" && <CircleDashed aria-hidden />}
      {label}
    </Badge>
  );
}
