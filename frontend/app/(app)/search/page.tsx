import type { Metadata } from "next";
import { Search } from "lucide-react";
import { PageHeader } from "@/components/shared/page-header";
import { FeaturePlaceholder } from "@/components/shared/feature-placeholder";

export const metadata: Metadata = { title: "Search" };

export default function SearchPage() {
  return (
    <>
      <PageHeader
        title="Search"
        description="Find the exact passage across everything you've indexed."
      />
      <FeaturePlaceholder
        icon={Search}
        title="Knowledge search"
        description="Search will be available here once Lumora is connected to your account."
        capabilities={[
          "Search one workspace, or narrow results to a single document",
          "See each result's file name, position in the file and relevance score",
          "Only indexed documents are searched",
        ]}
      />
    </>
  );
}
