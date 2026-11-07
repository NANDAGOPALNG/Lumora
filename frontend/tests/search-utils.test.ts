import { describe, expect, it } from "vitest";
import { PREVIEW_LENGTH, formatScore, isTruncated, previewOf, sameSearch, sameSelection } from "@/lib/search";

const params = { query: "auth", workspaceId: "w1", documentId: null, topK: 5 };

describe("formatScore", () => {
  it("shows the raw number with fixed precision, never as a percentage", () => {
    expect(formatScore(0.87312)).toBe("0.873");
    expect(formatScore(3)).toBe("3.000");
    expect(formatScore(-1.5)).toBe("-1.500");
    expect(formatScore(0.87312)).not.toContain("%");
    expect(formatScore(Number.NaN)).toBe("n/a");
  });
});

describe("passage preview", () => {
  it("leaves short passages whole", () => {
    expect(isTruncated("short")).toBe(false);
    expect(previewOf("  short  ")).toBe("short");
    expect(isTruncated("x".repeat(PREVIEW_LENGTH))).toBe(false);
  });

  it("truncates long passages with an ellipsis", () => {
    const long = "word ".repeat(200);
    expect(isTruncated(long)).toBe(true);
    const preview = previewOf(long);
    expect(preview.endsWith("…")).toBe(true);
    expect(preview.length).toBeLessThanOrEqual(PREVIEW_LENGTH + 1);
  });
});

describe("selection comparison", () => {
  it("tells whether results belong to the current selection", () => {
    expect(sameSelection(params, { workspaceId: "w1", documentId: null, topK: 5 })).toBe(true);
    expect(sameSelection(params, { workspaceId: "w2", documentId: null, topK: 5 })).toBe(false);
    expect(sameSelection(params, { workspaceId: "w1", documentId: "d1", topK: 5 })).toBe(false);
    expect(sameSelection(params, { workspaceId: "w1", documentId: null, topK: 10 })).toBe(false);
  });

  it("tells whether two searches are identical", () => {
    expect(sameSearch(params, { ...params })).toBe(true);
    expect(sameSearch(params, { ...params, query: "other" })).toBe(false);
  });
});
