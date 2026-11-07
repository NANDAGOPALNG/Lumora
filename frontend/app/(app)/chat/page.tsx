import type { Metadata } from "next";
import { Suspense } from "react";
import { ChatView } from "@/components/chat/chat-view";
import { Skeleton } from "@/components/ui/skeleton";

export const metadata: Metadata = { title: "AI Chat" };

export default function ChatPage() {
  // ChatView reads the open conversation from the URL (?c=), which needs a Suspense boundary.
  return (
    <Suspense fallback={<Skeleton className="h-64 w-full rounded-xl" />}>
      <ChatView />
    </Suspense>
  );
}
