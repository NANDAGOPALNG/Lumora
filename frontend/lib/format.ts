const UNKNOWN = "Unknown date";

function format(iso: string, options: Intl.DateTimeFormatOptions): string {
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return UNKNOWN;
  return new Intl.DateTimeFormat(undefined, options).format(date);
}

export const formatDate = (iso: string) => format(iso, { dateStyle: "medium" });

export const formatDateTime = (iso: string) =>
  format(iso, { dateStyle: "long", timeStyle: "short" });
