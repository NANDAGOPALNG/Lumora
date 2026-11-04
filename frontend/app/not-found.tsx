import Link from "next/link";
import { Button } from "@/components/ui/button";
import { LogoMark } from "@/components/layout/logo";

export default function NotFound() {
  return (
    <main className="flex min-h-dvh flex-col items-center justify-center gap-6 px-6 text-center">
      <LogoMark className="size-10" />
      <div className="space-y-2">
        <h1 className="font-serif text-4xl font-medium tracking-tight">
          Page not found
        </h1>
        <p className="max-w-sm text-sm text-muted-foreground">
          The page you&apos;re looking for doesn&apos;t exist or has moved.
        </p>
      </div>
      <Button asChild>
        <Link href="/">Back to dashboard</Link>
      </Button>
    </main>
  );
}
