"use client";

import { Copy } from "lucide-react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";

export function CopyButton({ value, label }: { value: string; label: string }) {
  async function copy() {
    try {
      await navigator.clipboard.writeText(value);
      toast.success("Copied to clipboard");
    } catch {
      toast.error("Couldn’t copy. Select the text and copy it manually.");
    }
  }

  return (
    <Button variant="ghost" size="icon-sm" aria-label={label} onClick={() => void copy()}>
      <Copy />
    </Button>
  );
}
