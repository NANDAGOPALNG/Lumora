"use client";

import { useState } from "react";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { describeApiError } from "@/lib/api/errors";
import { cn } from "@/lib/utils";
import { WORKSPACE_NAME_MAX, nameLength, validateWorkspaceName } from "@/lib/workspaces";

interface WorkspaceNameDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  title: string;
  description: string;
  submitLabel: string;
  /** Pre-filled name. When set, submitting an unchanged name is disabled. */
  initialName?: string;
  /** Resolve to close the dialog; throw to show the error inside it. */
  onSubmit: (name: string) => Promise<void>;
}

interface NameFormProps extends Pick<WorkspaceNameDialogProps, "initialName" | "onSubmit" | "submitLabel"> {
  onCancel: () => void;
  onPendingChange: (pending: boolean) => void;
}

function NameForm({ initialName = "", onSubmit, submitLabel, onCancel, onPendingChange }: NameFormProps) {
  const [value, setValue] = useState(initialName);
  const [touched, setTouched] = useState(false);
  const [pending, setPending] = useState(false);
  const [serverError, setServerError] = useState<string | null>(null);

  const validation = validateWorkspaceName(value);
  const unchanged = initialName !== "" && value.trim() === initialName.trim();
  const length = nameLength(value);
  // Over-length is flagged immediately; "required" waits until the field has been touched.
  const errorMessage = serverError ?? (touched || length > WORKSPACE_NAME_MAX ? validation : null);

  async function handleSubmit(event: React.FormEvent) {
    event.preventDefault();
    setTouched(true);
    if (validation !== null || unchanged || pending) return;

    setPending(true);
    onPendingChange(true);
    setServerError(null);
    try {
      await onSubmit(value.trim());
    } catch (error) {
      setServerError(describeApiError(error));
    } finally {
      setPending(false);
      onPendingChange(false);
    }
  }

  return (
    <form onSubmit={(event) => void handleSubmit(event)} className="grid gap-4" noValidate>
      <div className="grid gap-2">
        <div className="flex items-baseline justify-between">
          <label htmlFor="workspace-name" className="text-sm font-medium">
            Workspace name
          </label>
          <span
            className={cn(
              "text-xs tabular-nums text-muted-foreground",
              length > WORKSPACE_NAME_MAX && "text-destructive",
            )}
          >
            {length}/{WORKSPACE_NAME_MAX}
          </span>
        </div>
        <Input
          id="workspace-name"
          value={value}
          autoComplete="off"
          disabled={pending}
          aria-invalid={errorMessage !== null}
          aria-describedby={errorMessage ? "workspace-name-error" : undefined}
          onChange={(event) => {
            setValue(event.target.value);
            setServerError(null);
          }}
          onBlur={() => setTouched(true)}
          onFocus={(event) => event.currentTarget.select()}
        />
        {errorMessage && (
          <p id="workspace-name-error" role="alert" className="text-sm text-destructive">
            {errorMessage}
          </p>
        )}
      </div>
      <DialogFooter>
        <Button type="button" variant="outline" onClick={onCancel} disabled={pending}>
          Cancel
        </Button>
        <Button type="submit" loading={pending} disabled={validation !== null || unchanged}>
          {submitLabel}
        </Button>
      </DialogFooter>
    </form>
  );
}

/** Shared by "create" and "rename": one name field with validation and inline server errors. */
export function WorkspaceNameDialog({
  open,
  onOpenChange,
  title,
  description,
  submitLabel,
  initialName,
  onSubmit,
}: WorkspaceNameDialogProps) {
  const [pending, setPending] = useState(false);

  return (
    <Dialog
      open={open}
      // Don't let Esc, outside clicks or the close button interrupt an in-flight request.
      onOpenChange={(next) => {
        if (!next && pending) return;
        onOpenChange(next);
      }}
    >
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{title}</DialogTitle>
          <DialogDescription>{description}</DialogDescription>
        </DialogHeader>
        <NameForm
          initialName={initialName}
          submitLabel={submitLabel}
          onSubmit={onSubmit}
          onCancel={() => onOpenChange(false)}
          onPendingChange={setPending}
        />
      </DialogContent>
    </Dialog>
  );
}
