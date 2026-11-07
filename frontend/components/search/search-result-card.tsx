"use client";

import { useId, useState } from "react";
import { FileText } from "lucide-react";
import type { SearchSource } from "@/types/api";
import { Badge } from "@/components/ui/badge";
import { formatScore, isTruncated, previewOf } from "@/lib/search";

interface SearchResultCardProps {
  result: SearchSource;
  /** 1-based position in the backend's ordering (best first). */
  rank: number;
}

/** One retrieved passage, exactly as the backend returned it. */
export function SearchResultCard({ result, rank }: SearchResultCardProps) {
  const [expanded, setExpanded] = useState(false);
  const passageId = useId();
  const content = result.content?.trim() ?? "";
  const truncated = isTruncated(content);

  return (
    <li className="rounded-xl border bg-card p-4 sm:p-5">
      <div className="flex items-start gap-3">
        <span
          className="flex size-6 shrink-0 items-center justify-center rounded-md bg-secondary text-xs font-medium text-muted-foreground"
          aria-label={`Result ${rank}`}
        >
          {rank}
        </span>
        <div className="min-w-0 flex-1 space-y-3">
          <div className="space-y-1.5">
            <h3 className="flex items-center gap-2 text-sm font-semibold">
              <FileText className="size-4 shrink-0 text-muted-foreground" aria-hidden />
              <span className="truncate" title={result.filename}>
                {result.filename}
              </span>
            </h3>
            <p className="flex flex-wrap items-center gap-x-2 gap-y-1 text-xs text-muted-foreground">
              {result.source && <Badge className="uppercase">{result.source}</Badge>}
              <span>Chunk {result.chunk_index}</span>
              <span aria-hidden>·</span>
              <span>Score {formatScore(result.score)}</span>
            </p>
          </div>

          {content ? (
            <p
              id={passageId}
              className="whitespace-pre-wrap text-sm leading-relaxed [overflow-wrap:anywhere]"
            >
              {expanded || !truncated ? content : previewOf(content)}
            </p>
          ) : (
            <p className="text-sm text-muted-foreground">The passage text isn’t available for this result.</p>
          )}

          {truncated && (
            <button
              type="button"
              aria-expanded={expanded}
              aria-controls={passageId}
              onClick={() => setExpanded((open) => !open)}
              className="rounded-sm text-xs font-medium underline-offset-2 hover:underline"
            >
              {expanded ? "Show less" : "Show full passage"}
            </button>
          )}
        </div>
      </div>
    </li>
  );
}
