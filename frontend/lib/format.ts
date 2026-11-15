const UNKNOWN = "Unknown date";

function format(iso: string, options: Intl.DateTimeFormatOptions): string {
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return UNKNOWN;
  return new Intl.DateTimeFormat(undefined, options).format(date);
}

export const formatDate = (iso: string) => format(iso, { dateStyle: "medium" });

export const formatDateTime = (iso: string) =>
  format(iso, { dateStyle: "long", timeStyle: "short" });

export const formatShortDateTime = (iso: string) =>
  format(iso, { month: "short", day: "numeric", hour: "numeric", minute: "2-digit" });

const MINUTE = 60;
const HOUR = 60 * MINUTE;
const DAY = 24 * HOUR;

/**
 * "just now", "5 minutes ago", "2 days ago"; older than a week (or in the far future) falls back
 * to a short absolute date so the value stays meaningful. `now` is injectable for tests.
 */
export function formatRelativeTime(iso: string, now: number = Date.now()): string {
  const time = new Date(iso).getTime();
  if (Number.isNaN(time)) return UNKNOWN;
  const seconds = Math.round((now - time) / 1000);
  if (seconds < -MINUTE || seconds >= 7 * DAY) return format(iso, { dateStyle: "medium" });
  if (seconds < 45) return "just now";

  const rtf = new Intl.RelativeTimeFormat("en", { numeric: "always" });
  if (seconds < HOUR) return rtf.format(-Math.max(1, Math.round(seconds / MINUTE)), "minute");
  if (seconds < DAY) return rtf.format(-Math.round(seconds / HOUR), "hour");
  return rtf.format(-Math.round(seconds / DAY), "day");
}
