import type { Metadata } from "next";
import { MessageSquare } from "lucide-react";
import { PageHeader } from "@/components/shared/page-header";
import { FeaturePlaceholder } from "@/components/shared/feature-placeholder";

export const metadata: Metadata = { title: "AI Chat" };

export default function ChatPage() {
  return (
    <>
      <PageHeader
        title="AI Chat"
        description="Ask questions and get answers drawn from your own documents."
      />
      <FeaturePlaceholder
        icon={MessageSquare}
        title="Chat with your knowledge base"
        description="Conversations will be available here once Lumora is connected to your account."
        capabilities={[
          "Ask within a workspace, or limit a question to a single document",
          "See the passages and files each answer is based on",
          "Return to earlier conversations or delete them",
        ]}
      />
    </>
  );
}
