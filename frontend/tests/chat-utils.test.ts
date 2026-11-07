import { describe, expect, it } from "vitest";
import { buildThread, conversationLabel, countAnswers, firstQuestion } from "@/lib/chat";
import { conversation, source } from "./fake-backend";

const detail = (turns: Array<[string, string]>) => {
  const { id, title, created_at, messages } = conversation(1, turns);
  return { id, title, created_at, messages };
};

describe("buildThread", () => {
  it("attaches sources to the matching answer by order, and only to answers", () => {
    const { messages } = detail([["q1", "a1"], ["q2", "a2"], ["q3", "a3"]]);
    const thread = buildThread(messages, { 0: [source(1, "a.pdf")], 2: [source(2, "b.md")] });
    expect(thread.map((m) => m.role)).toEqual(["user", "assistant", "user", "assistant", "user", "assistant"]);
    expect(thread[1].sources?.[0].filename).toBe("a.pdf");
    expect(thread[3].sources).toBeUndefined(); // never invented for answers without any
    expect(thread[5].sources?.[0].filename).toBe("b.md");
    expect(thread[0].sources).toBeUndefined();
  });

  it("counts answers", () => {
    expect(countAnswers(detail([["q1", "a1"], ["q2", "a2"]]).messages)).toBe(2);
  });
});

describe("conversation labels", () => {
  it("uses the title when the backend provides one", () => {
    const c = conversation(1, [["q", "a"]]);
    expect(conversationLabel({ id: c.id, title: "  Quarterly review ", created_at: c.created_at })).toBe("Quarterly review");
  });

  it("falls back to the first question once the conversation is known", () => {
    const d = detail([["What changed in Q3?", "a"]]);
    expect(conversationLabel({ id: d.id, title: null, created_at: d.created_at }, d)).toBe("What changed in Q3?");
  });

  it("truncates long questions", () => {
    const d = detail([["x".repeat(200), "a"]]);
    const label = firstQuestion(d)!;
    expect(label.length).toBeLessThanOrEqual(61);
    expect(label.endsWith("…")).toBe(true);
  });

  it("falls back to the start time when nothing else is known", () => {
    const c = conversation(1, [["q", "a"]]);
    expect(conversationLabel({ id: c.id, title: null, created_at: c.created_at })).toMatch(/^Conversation · /);
  });
});
