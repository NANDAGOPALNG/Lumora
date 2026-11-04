"use client";

import { useState } from "react";
import { cn } from "@/lib/utils";

interface UserAvatarProps {
  name: string;
  pictureUrl: string | null;
  className?: string;
}

function initials(name: string): string {
  const parts = name.trim().split(/\s+/).filter(Boolean);
  if (parts.length === 0) return "?";
  const first = parts[0][0];
  const last = parts.length > 1 ? parts[parts.length - 1][0] : "";
  return (first + last).toUpperCase();
}

/** Profile picture with an initials fallback if there's no picture or it fails to load. */
export function UserAvatar({ name, pictureUrl, className }: UserAvatarProps) {
  const safeUrl = pictureUrl?.startsWith("https://") ? pictureUrl : null;
  // Keyed by URL so a new picture gets a fresh attempt after an earlier failure.
  const [failedUrl, setFailedUrl] = useState<string | null>(null);
  const showImage = safeUrl !== null && failedUrl !== safeUrl;

  return (
    <span
      className={cn(
        "relative flex size-8 shrink-0 items-center justify-center overflow-hidden rounded-full bg-sidebar-accent text-xs font-semibold text-muted-foreground",
        className,
      )}
    >
      {showImage ? (
        // Google avatar hosts vary and are not worth proxying through next/image here.
        // eslint-disable-next-line @next/next/no-img-element
        <img
          src={safeUrl}
          alt=""
          referrerPolicy="no-referrer"
          className="size-full object-cover"
          onError={() => setFailedUrl(safeUrl)}
        />
      ) : (
        <span aria-hidden>{initials(name)}</span>
      )}
    </span>
  );
}
