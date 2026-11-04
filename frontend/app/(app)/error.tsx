"use client";

import { TriangleAlert } from "lucide-react";
import { Button } from "@/components/ui/button";
import { EmptyState } from "@/components/shared/empty-state";

export default function Error({ reset }: { error: Error; reset: () => void }) {
  return (
    <EmptyState
      icon={TriangleAlert}
      title="Something went wrong"
      description="This page failed to load. Try again, and if the problem continues, reload the app."
      action={<Button onClick={reset}>Try again</Button>}
    />
  );
}
