import { Fragment } from "react";
import { cn } from "@/lib/utils";

interface MessageContentProps {
  text: string;
  /** Number of sources available for this answer; "[n]" markers beyond it stay plain text. */
  sourceCount?: number;
  onCite?: (sourceNumber: number) => void;
}

type Block =
  | { kind: "paragraph"; lines: string[] }
  | { kind: "heading"; text: string }
  | { kind: "list"; ordered: boolean; items: string[] }
  | { kind: "code"; text: string };

const BULLET = /^\s*[-*•]\s+(.*)$/;
const NUMBERED = /^\s*\d+[.)]\s+(.*)$/;
const HEADING = /^#{1,6}\s+(.*)$/;

/**
 * A deliberately small, safe Markdown subset (paragraphs, headings, lists, code, bold, italic,
 * inline code). It builds React elements only, never raw HTML. Links and tables are shown as text.
 */
function parseBlocks(text: string): Block[] {
  const blocks: Block[] = [];
  const lines = text.replace(/\r\n/g, "\n").split("\n");
  let index = 0;

  while (index < lines.length) {
    const line = lines[index];

    if (line.trim().startsWith("```")) {
      const code: string[] = [];
      index += 1;
      while (index < lines.length && !lines[index].trim().startsWith("```")) {
        code.push(lines[index]);
        index += 1;
      }
      index += 1; // closing fence (or end of text)
      blocks.push({ kind: "code", text: code.join("\n") });
      continue;
    }

    if (line.trim() === "") {
      index += 1;
      continue;
    }

    const heading = line.match(HEADING);
    if (heading) {
      blocks.push({ kind: "heading", text: heading[1] });
      index += 1;
      continue;
    }

    const bullet = line.match(BULLET);
    const numbered = line.match(NUMBERED);
    if (bullet || numbered) {
      const ordered = !bullet;
      const pattern = ordered ? NUMBERED : BULLET;
      const items: string[] = [];
      while (index < lines.length) {
        const match = lines[index].match(pattern);
        if (!match) break;
        items.push(match[1]);
        index += 1;
      }
      blocks.push({ kind: "list", ordered, items });
      continue;
    }

    const paragraph: string[] = [];
    while (
      index < lines.length &&
      lines[index].trim() !== "" &&
      !lines[index].trim().startsWith("```") &&
      !HEADING.test(lines[index]) &&
      !BULLET.test(lines[index]) &&
      !NUMBERED.test(lines[index])
    ) {
      paragraph.push(lines[index]);
      index += 1;
    }
    blocks.push({ kind: "paragraph", lines: paragraph });
  }

  return blocks;
}

const INLINE = /(`[^`\n]+`|\*\*[^*\n]+\*\*|\*[^*\s][^*\n]*\*|\[\d+\])/g;

function renderInline(text: string, sourceCount: number, onCite?: (n: number) => void): React.ReactNode[] {
  return text.split(INLINE).map((part, index) => {
    if (!part) return null;
    if (part.startsWith("`") && part.endsWith("`") && part.length > 2) {
      return (
        <code key={index} className="rounded bg-secondary px-1 py-0.5 font-mono text-[0.85em]">
          {part.slice(1, -1)}
        </code>
      );
    }
    if (part.startsWith("**") && part.endsWith("**") && part.length > 4) {
      return <strong key={index}>{part.slice(2, -2)}</strong>;
    }
    if (part.startsWith("*") && part.endsWith("*") && part.length > 2) {
      return <em key={index}>{part.slice(1, -1)}</em>;
    }
    const citation = part.match(/^\[(\d+)\]$/);
    if (citation) {
      const number = Number(citation[1]);
      // Only link a marker to a source that really exists; otherwise leave the text alone.
      if (onCite && number >= 1 && number <= sourceCount) {
        return (
          <button
            key={index}
            type="button"
            onClick={() => onCite(number)}
            aria-label={`Show source ${number}`}
            className="mx-0.5 inline-flex min-w-5 items-center justify-center rounded-sm bg-brand-muted px-1 text-xs font-medium text-foreground transition-colors hover:bg-brand/40"
          >
            {number}
          </button>
        );
      }
    }
    return <Fragment key={index}>{part}</Fragment>;
  });
}

export function MessageContent({ text, sourceCount = 0, onCite }: MessageContentProps) {
  const blocks = parseBlocks(text);

  return (
    <div className="space-y-3 text-sm leading-relaxed [overflow-wrap:anywhere]">
      {blocks.map((block, index) => {
        switch (block.kind) {
          case "code":
            return (
              <pre
                key={index}
                className="overflow-x-auto rounded-lg border bg-secondary p-3 font-mono text-xs leading-relaxed"
              >
                <code>{block.text}</code>
              </pre>
            );
          case "heading":
            return (
              <p key={index} className="font-semibold">
                {renderInline(block.text, sourceCount, onCite)}
              </p>
            );
          case "list": {
            const List = block.ordered ? "ol" : "ul";
            return (
              <List
                key={index}
                className={cn("space-y-1 pl-5", block.ordered ? "list-decimal" : "list-disc")}
              >
                {block.items.map((item, itemIndex) => (
                  <li key={itemIndex}>{renderInline(item, sourceCount, onCite)}</li>
                ))}
              </List>
            );
          }
          case "paragraph":
            return (
              <p key={index}>
                {block.lines.map((line, lineIndex) => (
                  <Fragment key={lineIndex}>
                    {lineIndex > 0 && <br />}
                    {renderInline(line, sourceCount, onCite)}
                  </Fragment>
                ))}
              </p>
            );
        }
      })}
    </div>
  );
}
