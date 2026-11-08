"use client";

import { useState } from "react";
import { toast } from "sonner";
import type { ConnectorResponse, WorkspaceResponse } from "@/types/api";
import { useGitHubConnectorActions } from "@/hooks/use-connectors";
import { describeApiError } from "@/lib/api/errors";
import { normaliseRepoInput, validateRepoFullName, validateToken } from "@/lib/connectors";
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
import { Select } from "@/components/ui/select";
import { TokenField } from "@/components/integrations/token-field";

interface ConnectGitHubDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  workspaces: WorkspaceResponse[];
  defaultWorkspaceId: string | null;
  onConnected: (connector: ConnectorResponse) => void;
}

interface FormProps extends Pick<ConnectGitHubDialogProps, "workspaces" | "defaultWorkspaceId" | "onConnected"> {
  onCancel: () => void;
  onPendingChange: (pending: boolean) => void;
}

function ConnectForm({ workspaces, defaultWorkspaceId, onConnected, onCancel, onPendingChange }: FormProps) {
  const actions = useGitHubConnectorActions();
  const [workspaceId, setWorkspaceId] = useState(defaultWorkspaceId ?? "");
  const [repo, setRepo] = useState("");
  const [token, setToken] = useState(""); // lives only in this form and is cleared after the request
  const [name, setName] = useState("");
  const [touched, setTouched] = useState<Record<string, boolean>>({});
  const [pending, setPending] = useState(false);
  const [serverError, setServerError] = useState<string | null>(null);

  const errors = {
    workspace: workspaceId ? null : "Choose a workspace.",
    repo: validateRepoFullName(repo),
    token: validateToken(token),
  };
  const show = (field: keyof typeof errors) => (touched[field] ? errors[field] : null);
  const touch = (field: string) => setTouched((current) => ({ ...current, [field]: true }));

  async function handleSubmit(event: React.FormEvent) {
    event.preventDefault();
    if (pending) return;
    setTouched({ workspace: true, repo: true, token: true });
    if (errors.workspace || errors.repo || errors.token) return;

    setPending(true);
    onPendingChange(true);
    setServerError(null);
    try {
      const created = await actions.connect({
        workspace_id: workspaceId,
        repo_full_name: normaliseRepoInput(repo),
        github_token: token.trim(),
        ...(name.trim() ? { connection_name: name.trim() } : {}),
      });
      toast.success(`Connected ${created.github_repo ?? created.connection_name}`);
      onConnected(created);
    } catch (error) {
      setServerError(describeApiError(error));
    } finally {
      setToken(""); // never keep the token once the request has finished, successful or not
      setPending(false);
      onPendingChange(false);
    }
  }

  return (
    <form onSubmit={(event) => void handleSubmit(event)} className="grid gap-4" noValidate>
      <div className="grid gap-2">
        <label htmlFor="connect-workspace" className="text-sm font-medium">
          Workspace
        </label>
        <Select
          id="connect-workspace"
          value={workspaceId}
          disabled={pending}
          aria-invalid={show("workspace") ? true : undefined}
          onChange={(event) => {
            setWorkspaceId(event.target.value);
            touch("workspace");
          }}
        >
          {workspaceId === "" && <option value="">Choose a workspace…</option>}
          {workspaces.map((workspace) => (
            <option key={workspace.id} value={workspace.id}>
              {workspace.name}
            </option>
          ))}
        </Select>
        {show("workspace") && (
          <p role="alert" className="text-sm text-destructive">
            {show("workspace")}
          </p>
        )}
      </div>

      <div className="grid gap-2">
        <label htmlFor="connect-repo" className="text-sm font-medium">
          Repository
        </label>
        <Input
          id="connect-repo"
          value={repo}
          disabled={pending}
          autoComplete="off"
          spellCheck={false}
          placeholder="owner/repository"
          aria-invalid={show("repo") ? true : undefined}
          onChange={(event) => setRepo(event.target.value)}
          onBlur={() => touch("repo")}
        />
        {show("repo") && (
          <p role="alert" className="text-sm text-destructive">
            {show("repo")}
          </p>
        )}
      </div>

      <TokenField
        id="connect-token"
        value={token}
        onChange={setToken}
        disabled={pending}
        error={show("token")}
        onBlur={() => touch("token")}
      />
      <p className="-mt-2 text-xs leading-relaxed text-muted-foreground">
        Use a token that can read the repository. Lumora only uses it to check access and import files, and
        doesn’t store it, so you’ll enter it again for every sync.
      </p>

      <div className="grid gap-2">
        <label htmlFor="connect-name" className="text-sm font-medium">
          Display name <span className="font-normal text-muted-foreground">(optional)</span>
        </label>
        <Input
          id="connect-name"
          value={name}
          disabled={pending}
          autoComplete="off"
          placeholder="Defaults to the repository name"
          onChange={(event) => setName(event.target.value)}
        />
      </div>

      {serverError && (
        <p role="alert" className="text-sm text-destructive">
          {serverError}
        </p>
      )}

      <DialogFooter>
        <Button type="button" variant="outline" onClick={onCancel} disabled={pending}>
          Cancel
        </Button>
        <Button type="submit" loading={pending}>
          Connect repository
        </Button>
      </DialogFooter>
    </form>
  );
}

export function ConnectGitHubDialog({
  open,
  onOpenChange,
  workspaces,
  defaultWorkspaceId,
  onConnected,
}: ConnectGitHubDialogProps) {
  const [pending, setPending] = useState(false);

  return (
    <Dialog
      open={open}
      // Don't let Esc or a stray click interrupt a request that is checking the token.
      onOpenChange={(next) => {
        if (!next && pending) return;
        onOpenChange(next);
      }}
    >
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Connect a GitHub repository</DialogTitle>
          <DialogDescription>
            Import a repository’s documentation and text files into a workspace so you can search and chat
            with them.
          </DialogDescription>
        </DialogHeader>
        <ConnectForm
          workspaces={workspaces}
          defaultWorkspaceId={defaultWorkspaceId}
          onConnected={(connector) => {
            onConnected(connector);
            onOpenChange(false);
          }}
          onCancel={() => onOpenChange(false)}
          onPendingChange={setPending}
        />
      </DialogContent>
    </Dialog>
  );
}
