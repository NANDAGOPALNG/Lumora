const stats = [
  { label: "Workspaces", hint: "Spaces you've created" },
  { label: "Documents", hint: "Files across all workspaces" },
  { label: "Indexed chunks", hint: "Passages available to search" },
  { label: "Conversations", hint: "Chats with your knowledge base" },
] as const;

/**
 * One divided panel rather than a row of separate cards. Values are
 * intentionally empty: no backend data is loaded in this phase.
 */
export function OverviewStats() {
  return (
    <section aria-labelledby="overview-heading">
      <h2 id="overview-heading" className="sr-only">
        Overview
      </h2>
      <dl className="grid grid-cols-2 overflow-hidden rounded-xl border bg-card lg:grid-cols-4">
        {stats.map((stat, index) => (
          <div
            key={stat.label}
            className={[
              "p-5",
              index % 2 === 1 ? "border-l" : "",
              index >= 2 ? "border-t lg:border-t-0" : "",
              index >= 1 ? "lg:border-l" : "",
            ].join(" ")}
          >
            <dt className="text-sm text-muted-foreground">{stat.label}</dt>
            <dd className="mt-2 font-serif text-3xl font-medium tracking-tight text-muted-foreground/60">
              <span aria-label="No data yet">—</span>
            </dd>
            <p className="mt-1 text-xs text-muted-foreground">{stat.hint}</p>
          </div>
        ))}
      </dl>
      <p className="mt-2.5 text-xs text-muted-foreground">
        Not connected to the backend yet, so no counts are shown.
      </p>
    </section>
  );
}
