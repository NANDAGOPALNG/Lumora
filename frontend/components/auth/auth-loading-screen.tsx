import { LogoMark } from "@/components/layout/logo";
import { Spinner } from "@/components/ui/spinner";

export function AuthLoadingScreen({ label = "Loading" }: { label?: string }) {
  return (
    <div className="flex min-h-dvh flex-col items-center justify-center gap-4 bg-background">
      <LogoMark className="size-10" />
      <div className="flex items-center gap-2 text-sm text-muted-foreground">
        <Spinner />
        <span>{label}…</span>
      </div>
    </div>
  );
}
