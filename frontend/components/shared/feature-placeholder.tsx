import type { LucideIcon } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";

interface FeaturePlaceholderProps {
  icon: LucideIcon;
  title: string;
  description: string;
  /** What this section will do, based on the backend's documented capabilities. */
  capabilities: string[];
}

/**
 * Honest stand-in for a section whose backend integration is not built yet.
 * It renders no fake data and no inert controls.
 */
export function FeaturePlaceholder({
  icon: Icon,
  title,
  description,
  capabilities,
}: FeaturePlaceholderProps) {
  return (
    <Card className="max-w-2xl">
      <CardHeader className="flex-row items-start gap-4">
        <span className="flex size-10 shrink-0 items-center justify-center rounded-lg bg-secondary text-muted-foreground">
          <Icon className="size-5" aria-hidden />
        </span>
        <div className="space-y-1.5">
          <div className="flex items-center gap-2">
            <CardTitle>{title}</CardTitle>
            <Badge variant="brand">Not available yet</Badge>
          </div>
          <CardDescription className="leading-relaxed">{description}</CardDescription>
        </div>
      </CardHeader>
      <CardContent>
        <ul className="space-y-2 border-t pt-4 text-sm">
          {capabilities.map((capability) => (
            <li key={capability} className="flex gap-3 text-muted-foreground">
              <span className="mt-2 size-1 shrink-0 rounded-full bg-brand" aria-hidden />
              {capability}
            </li>
          ))}
        </ul>
      </CardContent>
    </Card>
  );
}
