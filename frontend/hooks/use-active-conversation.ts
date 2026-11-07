"use client";

import { useCallback, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { isUuid } from "@/lib/workspaces";

/**
 * The open conversation lives in the URL (?c=<id>) so a refresh or shared tab restores it.
 *
 * Changing the URL is asynchronous, and without care the page would briefly show the previous
 * conversation (or an empty one) while it catches up. So `open` also records the target
 * immediately; that choice is dropped as soon as the URL reflects it or changes for any reason.
 */
export function useActiveConversation() {
  const router = useRouter();
  const raw = useSearchParams().get("c");
  const urlId = raw && isUuid(raw) ? raw : null;
  const [requested, setRequested] = useState<{ id: string | null; urlWhenRequested: string | null } | null>(null);

  // Adjust state while rendering (React's documented pattern) once the URL has caught up.
  if (requested && urlId === requested.id) setRequested(null);

  const followsRequest = requested !== null && requested.urlWhenRequested === urlId;
  const conversationId = followsRequest ? requested.id : urlId;

  const open = useCallback(
    (id: string | null) => {
      setRequested({ id, urlWhenRequested: urlId });
      router.replace(id ? `/chat?c=${encodeURIComponent(id)}` : "/chat");
    },
    [router, urlId],
  );

  return { conversationId, invalid: !followsRequest && raw !== null && urlId === null, open };
}
