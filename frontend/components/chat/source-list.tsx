"use client";

import { ChevronDown, FileText } from "lucide-react";
import type { SearchSource } from "@/types/api";
import { cn } from "@/lib/utils";

interface SourceListProps {
  sources: SearchSource[];
  open: boolean;
  onOpenChange: (open: boolean) => void;
  /** Source numbers (1-based) whose excerpt is expanded. */
  expanded: number[];
  onToggleExcerpt: (sourceNumber: number) => void;
  /** Used to give each source row a unique id for the "[n]" citation markers. */
  idPrefix: string;
}

/** Shows exactly the sources the backend returned for an answer; nothing is inferred or invented. */
export function SourceList({ sources, open, onOpenChange, expanded, onToggleExcerpt, idPrefix }: SourceListProps) {
  if (sources.length === 0) {
    return <p className="text-xs text-muted-foreground">No sources were found for this answer.</p>;
  }

  return (
    <div>
      <button
        type="button"
        aria-expanded={open}
        onClick={() => onOpenChange(!open)}
        className="inline-flex items-center gap-1.5 rounded-md py-1 text-xs font-medium text-muted-foreground transition-colors hover:text-foreground"
      >
        <ChevronDown className={cn("size-3.5 transition-transform", !open && "-rotate-90")} aria-hidden />
        Sources ({sources.length})
      </button>

      {open && (
        <ol aria-label="Sources" className="mt-2 space-y-2">
          {sources.map((source, index) => {
            const number = index + 1;
            const isExpanded = expanded.includes(number);
            return (
              <li
                key={`${source.chunk_id}-${index}`}
                id={`${idPrefix}-source-${number}`}
                className="rounded-lg border bg-card p-3"
              >
                <div className="flex items-start gap-2.5">
                  <span className="flex size-5 shrink-0 items-center justify-center rounded-sm bg-brand-muted text-xs font-medium">
                    {number}
                  </span>
                  <div className="min-w-0 flex-1">
                    <p className="flex items-center gap-1.5 text-sm font-medium">
                      <FileText className="size-3.5 shrink-0 text-muted-foreground" aria-hidden />
                      <span className="truncate" title={source.filename}>
                        {source.filename}
                      </span>
                    </p>
                    <p className="mt-0.5 flex flex-wrap gap-x-2 text-xs text-muted-foreground">
                      <span>Chunk {source.chunk_index}</span>
                      <span aria-hidden>·</span>
                      <span>Score {source.score.toFixed(2)}</span>
                      {source.source && (
                        <>
                          <span aria-hidden>·</span>
                          <span className="uppercase">{source.source}</span>
                        </>
                      )}
                    </p>
                    <button
                      type="button"
                      aria-expanded={isExpanded}
                      onClick={() => onToggleExcerpt(number)}
                      className="mt-1.5 text-xs font-medium underline-offset-2 hover:underline"
                    >
                      {isExpanded ? "Hide excerpt" : "Show excerpt"}
                    </button>
                    {isExpanded && (
                      <pre className="mt-2 max-h-56 overflow-auto whitespace-pre-wrap rounded-md bg-secondary p-3 font-sans text-xs leading-relaxed [overflow-wrap:anywhere]">
                        {source.content?.trim() || "The excerpt isn’t available for this source."}
                      </pre>
                    )}
                  </div>
                </div>
              </li>
            );
          })}
        </ol>
      )}
    </div>
  );
}
