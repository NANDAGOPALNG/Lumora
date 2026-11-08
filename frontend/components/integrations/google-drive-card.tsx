import { Cloud } from "lucide-react";
import { Badge } from "@/components/ui/badge";

/**
 * Deliberately not connectable. The backend only accepts a short-lived Drive access token supplied
 * with each request and has no Google OAuth consent/callback or refresh flow, so a working
 * connection can't be offered here yet. No button, no token form, no fake "connected" state.
 */
export function GoogleDriveCard() {
  return (
    <section aria-labelledby="drive-heading" className="rounded-xl border bg-card p-5">
      <div className="flex gap-4">
        <span className="flex size-10 shrink-0 items-center justify-center rounded-lg bg-secondary text-muted-foreground">
          <Cloud className="size-5" aria-hidden />
        </span>
        <div className="min-w-0 space-y-1.5">
          <div className="flex flex-wrap items-center gap-2">
            <h2 id="drive-heading" className="text-[15px] font-semibold">
              Google Drive
            </h2>
            <Badge variant="brand">OAuth setup required</Badge>
          </div>
          <p className="text-sm leading-relaxed text-muted-foreground">
            Importing from Google Drive needs a Google sign-in and authorisation flow that Lumora doesn’t
            have yet. Until it is built, Drive can’t be connected from here.
          </p>
        </div>
      </div>
    </section>
  );
}
