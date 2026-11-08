import type { GitHubSyncResponse } from "@/types/api";

const STATS: Array<{ key: keyof GitHubSyncResponse; label: string; hint?: string }> = [
  { key: "files_discovered", label: "Discovered", hint: "Supported files found in the repository" },
  { key: "files_added", label: "Added" },
  { key: "files_updated", label: "Updated" },
  { key: "files_deleted", label: "Deleted", hint: "Imported earlier, no longer in the repository" },
  { key: "files_unchanged", label: "Unchanged" },
  { key: "files_skipped", label: "Skipped", hint: "Couldn’t be fetched, parsed or indexed" },
];

/** The finished summary the backend returns; there is no live progress to show. */
export function SyncSummary({ summary }: { summary: GitHubSyncResponse }) {
  return (
    <div className="space-y-3">
      <p className="text-sm">
        Sync of <span className="font-medium [overflow-wrap:anywhere]">{summary.repository}</span>:{" "}
        <span className="font-medium capitalize">{summary.status}</span>
      </p>
      <dl className="grid grid-cols-2 gap-px overflow-hidden rounded-lg border bg-border sm:grid-cols-3">
        {STATS.map(({ key, label, hint }) => (
          <div key={key} className="bg-card p-3" title={hint}>
            <dt className="text-xs text-muted-foreground">{label}</dt>
            <dd className="mt-1 font-serif text-2xl font-medium tabular-nums">{String(summary[key])}</dd>
          </div>
        ))}
      </dl>
    </div>
  );
}
