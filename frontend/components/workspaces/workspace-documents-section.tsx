import { FileText } from "lucide-react";
import { EmptyState } from "@/components/shared/empty-state";

/**
 * Slot for this workspace's documents. Document listing isn't connected yet,
 * so this deliberately does not claim the workspace has no documents.
 * It will receive the workspace id when document management is built.
 */
export function WorkspaceDocumentsSection() {
  return (
    <section aria-labelledby="documents-heading">
      <h2 id="documents-heading" className="mb-3 text-[15px] font-semibold">
        Documents
      </h2>
      <EmptyState
        icon={FileText}
        title="Documents aren’t shown here yet"
        description="Uploading and listing this workspace’s documents arrives in an upcoming release."
        className="py-10"
      />
    </section>
  );
}
