import { cn } from "@/lib/utils";

export function LogoMark({ className }: { className?: string }) {
  return (
    <svg
      viewBox="0 0 28 28"
      aria-hidden
      className={cn("size-7 shrink-0", className)}
    >
      <rect width="28" height="28" rx="7" className="fill-foreground" />
      <rect x="7" y="7" width="14" height="3" rx="1.5" className="fill-brand" />
      <rect x="7" y="12.5" width="10" height="3" rx="1.5" className="fill-background" />
      <rect x="7" y="18" width="6" height="3" rx="1.5" className="fill-background" />
    </svg>
  );
}

export function Logo({ showWordmark = true }: { showWordmark?: boolean }) {
  return (
    <span className="flex items-center gap-2.5">
      <LogoMark />
      {showWordmark ? (
        <span className="font-serif text-[21px] font-medium leading-none tracking-tight">
          Lumora
        </span>
      ) : (
        <span className="sr-only">Lumora</span>
      )}
    </span>
  );
}
