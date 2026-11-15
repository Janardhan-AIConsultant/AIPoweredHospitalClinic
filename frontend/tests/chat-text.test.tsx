import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { ChatText, normalizeChatText, parseBlocks } from "@/components/chat-text";

describe("normalizeChatText", () => {
  it("turns non-breaking hyphens and spaces into plain ones so dates read and copy correctly", () => {
    expect(normalizeChatText("2026\u201111\u201116 at 10:00\u00a0AM")).toBe("2026-11-16 at 10:00 AM");
  });

  it("turns markdown headings into bold", () => {
    expect(normalizeChatText("## Slots")).toBe("**Slots**");
  });
});

describe("parseBlocks", () => {
  it("separates paragraphs and groups consecutive list items", () => {
    const blocks = parseBlocks("Open slots:\n\n- 10:00\n- 10:30\n\nWhich one?");
    expect(blocks.map((b) => b.kind)).toEqual(["p", "ul", "p"]);
    expect(blocks[1]).toEqual({ kind: "ul", items: ["10:00", "10:30"] });
  });

  it("recognises numbered lists and other bullet glyphs", () => {
    expect(parseBlocks("1. one\n2) two")[0]).toEqual({ kind: "ol", items: ["one", "two"] });
    expect(parseBlocks("• a\n* b")[0]).toEqual({ kind: "ul", items: ["a", "b"] });
  });
});

describe("ChatText", () => {
  it("renders bold and lists as elements without leftover asterisks", () => {
    const { container } = render(
      <ChatText text={"Dr. **Priya Sharma** is free.\n\n- 10:00 AM\n- 10:30 AM"} />,
    );
    expect(screen.getByText("Priya Sharma").tagName).toBe("STRONG");
    expect(container.querySelectorAll("li")).toHaveLength(2);
    expect(container.textContent).not.toContain("*");
  });

  it("never injects HTML or links from model output", () => {
    const { container } = render(<ChatText text={'<img src=x onerror=alert(1)> [x](http://evil.test)'} />);
    expect(container.querySelector("img")).toBeNull();
    expect(container.querySelector("a")).toBeNull();
    expect(container.textContent).toContain("<img");
  });

  it("drops unmatched bold markers instead of showing them", () => {
    const { container } = render(<ChatText text="Fee is **₹600" />);
    expect(container.textContent).toBe("Fee is ₹600");
  });
});
