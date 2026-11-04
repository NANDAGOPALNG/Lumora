import type { Metadata } from "next";
import { PageHeader } from "@/components/shared/page-header";
import { ThemeSelector } from "@/components/shared/theme-selector";
import { Badge } from "@/components/ui/badge";

export const metadata: Metadata = { title: "Settings" };

export default function SettingsPage() {
  return (
    <>
      <PageHeader title="Settings" description="Personalise how Lumora looks and behaves." />
      <div className="max-w-2xl space-y-10">
        <section aria-labelledby="appearance-heading" className="space-y-4">
          <div className="space-y-1">
            <h2 id="appearance-heading" className="text-[15px] font-semibold">
              Appearance
            </h2>
            <p className="text-sm text-muted-foreground">
              Choose a theme, or follow your device setting.
            </p>
          </div>
          <ThemeSelector />
        </section>

        <section aria-labelledby="account-heading" className="space-y-1 border-t pt-8">
          <div className="flex items-center gap-2">
            <h2 id="account-heading" className="text-[15px] font-semibold">
              Account
            </h2>
            <Badge variant="outline">Not available yet</Badge>
          </div>
          <p className="text-sm text-muted-foreground">
            Profile details and sign-out will appear here once you can sign in.
          </p>
        </section>
      </div>
    </>
  );
}
