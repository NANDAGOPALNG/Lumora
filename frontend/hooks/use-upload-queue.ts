"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { useReindexDocument, useUploadDocument } from "@/hooks/use-documents";
import { describeApiError } from "@/lib/api/errors";
import { validateFile } from "@/lib/documents";

export type UploadItemStatus =
  | "rejected" // failed client-side validation; never sent
  | "queued"
  | "uploading"
  | "indexing"
  | "uploaded" // stored, not indexed (auto-index was off)
  | "indexed"
  | "failed";

export interface UploadItem {
  id: string;
  workspaceId: string;
  file: File;
  status: UploadItemStatus;
  /** Upload progress, 0-1. */
  progress: number;
  error: string | null;
  documentId: string | null;
  /** Which step failed, so "retry" repeats the right one. */
  failedStage: "upload" | "index" | null;
}

const isActive = (item: UploadItem) =>
  item.status === "queued" || item.status === "uploading" || item.status === "indexing";

const sameFile = (a: File, b: File) =>
  a.name === b.name && a.size === b.size && a.lastModified === b.lastModified;

let nextItemId = 0;

/**
 * Sequential upload (and optional index) pipeline. Files are validated first, then handled
 * one at a time: indexing is CPU-heavy on the server, so running files in parallel would only
 * make each request slower. State lives in a ref so the loop always sees the latest queue.
 */
export function useUploadQueue({ autoIndex }: { autoIndex: boolean }) {
  const upload = useUploadDocument();
  const reindex = useReindexDocument();
  const [items, setItems] = useState<UploadItem[]>([]);
  const itemsRef = useRef<UploadItem[]>([]);
  const controllers = useRef(new Map<string, AbortController>());
  const draining = useRef(false);
  const autoIndexRef = useRef(autoIndex);

  useEffect(() => {
    autoIndexRef.current = autoIndex;
  }, [autoIndex]);

  // Abort in-flight uploads if the user leaves the page.
  useEffect(() => {
    const active = controllers.current;
    return () => active.forEach((controller) => controller.abort());
  }, []);

  const commit = useCallback((next: UploadItem[]) => {
    itemsRef.current = next;
    setItems(next);
  }, []);

  const update = useCallback(
    (id: string, patch: Partial<UploadItem>) => {
      if (!itemsRef.current.some((item) => item.id === id)) return;
      commit(itemsRef.current.map((item) => (item.id === id ? { ...item, ...patch } : item)));
    },
    [commit],
  );

  const runIndex = useCallback(
    async (id: string) => {
      const item = itemsRef.current.find((candidate) => candidate.id === id);
      if (!item?.documentId) return;
      update(id, { status: "indexing", error: null, failedStage: null });
      try {
        await reindex.mutateAsync({ id: item.documentId, workspaceId: item.workspaceId });
        update(id, { status: "indexed" });
      } catch (error) {
        update(id, { status: "failed", failedStage: "index", error: describeApiError(error) });
      }
    },
    [reindex, update],
  );

  const processItem = useCallback(
    async (id: string) => {
      const item = itemsRef.current.find((candidate) => candidate.id === id);
      if (!item) return;

      const controller = new AbortController();
      controllers.current.set(id, controller);
      update(id, { status: "uploading", progress: 0, error: null, failedStage: null });
      try {
        const created = await upload.mutateAsync({
          workspaceId: item.workspaceId,
          file: item.file,
          signal: controller.signal,
          onProgress: (fraction) => update(id, { progress: fraction }),
        });
        update(id, { documentId: created.id, progress: 1 });
      } catch (error) {
        if (error instanceof DOMException && error.name === "AbortError") {
          commit(itemsRef.current.filter((candidate) => candidate.id !== id)); // cancelled
        } else {
          update(id, { status: "failed", failedStage: "upload", error: describeApiError(error) });
        }
        return;
      } finally {
        controllers.current.delete(id);
      }

      if (autoIndexRef.current) await runIndex(id);
      else update(id, { status: "uploaded" });
    },
    [commit, runIndex, update, upload],
  );

  const drain = useCallback(async () => {
    if (draining.current) return; // one runner at a time: no accidental double uploads
    draining.current = true;
    try {
      for (;;) {
        const next = itemsRef.current.find((item) => item.status === "queued");
        if (!next) break;
        await processItem(next.id);
      }
    } finally {
      draining.current = false;
    }
  }, [processItem]);

  /** Returns how many files were ignored because the same file is already in progress. */
  const addFiles = useCallback(
    (files: File[], workspaceId: string): number => {
      let duplicates = 0;
      const added: UploadItem[] = [];
      for (const file of files) {
        const alreadyActive = [...itemsRef.current, ...added].some(
          (item) => item.workspaceId === workspaceId && isActive(item) && sameFile(item.file, file),
        );
        if (alreadyActive) {
          duplicates += 1;
          continue;
        }
        const validation = validateFile(file);
        added.push({
          id: `upload-${nextItemId++}`,
          workspaceId,
          file,
          status: validation.ok ? "queued" : "rejected",
          progress: 0,
          error: validation.ok ? null : validation.message,
          documentId: null,
          failedStage: null,
        });
      }
      if (added.length > 0) {
        commit([...itemsRef.current, ...added]);
        void drain();
      }
      return duplicates;
    },
    [commit, drain],
  );

  const retry = useCallback(
    (id: string) => {
      const item = itemsRef.current.find((candidate) => candidate.id === id);
      if (item?.status !== "failed") return;
      if (item.failedStage === "index") void runIndex(id);
      else {
        update(id, { status: "queued", error: null, failedStage: null, progress: 0 });
        void drain();
      }
    },
    [drain, runIndex, update],
  );

  const cancel = useCallback((id: string) => controllers.current.get(id)?.abort(), []);

  const remove = useCallback(
    (id: string) => {
      const item = itemsRef.current.find((candidate) => candidate.id === id);
      if (!item || item.status === "uploading" || item.status === "indexing") return;
      commit(itemsRef.current.filter((candidate) => candidate.id !== id));
    },
    [commit],
  );

  const clearFinished = useCallback(
    () => commit(itemsRef.current.filter(isActive)),
    [commit],
  );

  return { items, addFiles, retry, cancel, remove, clearFinished };
}
