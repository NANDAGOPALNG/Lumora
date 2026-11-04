"use client";

import { LogOut } from "lucide-react";
import { useAuth } from "@/hooks/use-auth";
import { UserAvatar } from "@/components/auth/user-avatar";
import { Button } from "@/components/ui/button";

export function AccountSummary() {
  const { user, signOut } = useAuth();
  if (!user) return null;

  return (
    <div className="flex max-w-md items-center gap-4 rounded-xl border bg-card p-4">
      <UserAvatar name={user.name} pictureUrl={user.picture_url} className="size-11 text-sm" />
      <div className="min-w-0 flex-1">
        <p className="truncate text-sm font-medium">{user.name}</p>
        <p className="truncate text-sm text-muted-foreground">{user.email}</p>
      </div>
      <Button variant="outline" size="sm" onClick={() => void signOut()}>
        <LogOut /> Sign out
      </Button>
    </div>
  );
}
