import type { Metadata } from "next";
import { FileText } from "lucide-react";
import { PageHeader } from "@/components/shared/page-header";
import { FeaturePlaceholder } from "@/components/shared/feature-placeholder";

export const metadata: Metadata = { title: "Documents" };

export default function DocumentsPage() {
  return (
    <>
      <PageHeader
        title="Documents"
        description="Upload files and make them searchable."
      />
      <FeaturePlaceholder
        icon={FileText}
        title="Document management"
        description="Uploads and indexing will be available here once Lumora is connected to your account."
        capabilities={[
          "Upload PDF, Word (.docx), text and Markdown files (20 MB limit by default)",
          "Follow each file's status: Uploaded, Processing, Indexed or Failed",
          "Index a file after upload, and re-index it if indexing fails",
          "Delete documents you no longer need",
        ]}
      />
    </>
  );
}
