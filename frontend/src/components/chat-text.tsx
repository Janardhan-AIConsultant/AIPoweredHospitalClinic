import { Fragment, type ReactNode } from "react";

/**
 * Renders the small subset of Markdown the assistant uses (paragraphs, bullet and numbered lists,
 * **bold**) as real elements. It never injects HTML, so model output cannot add markup or links.
 */

const BULLET = /^\s*(?:[-*•–]|\d+[.)])\s+(.*)$/;
const NUMBERED = /^\s*\d+[.)]\s+/;

/** Models emit non-breaking hyphens/spaces that look odd and break copy-paste of dates. */
export function normalizeChatText(text: string): string {
  return text
    .replace(/[‐‑‒]/g, "-")
    .replace(/[  ]/g, " ")
    .replace(/^#{1,6}\s+(.*)$/gm, "**$1**")
    .replace(/[ \t]+\n/g, "\n")
    .trim();
}

function inline(text: string, keyPrefix: string): ReactNode[] {
  return text.split(/(\*\*[^*\n]+\*\*)/g).map((part, i) =>
    part.startsWith("**") && part.endsWith("**") && part.length > 4 ? (
      <strong key={`${keyPrefix}-${i}`} className="font-semibold">
        {part.slice(2, -2)}
      </strong>
    ) : (
      <Fragment key={`${keyPrefix}-${i}`}>{part.replace(/\*\*/g, "")}</Fragment>
    ),
  );
}

export type Block =
  | { kind: "p"; lines: string[] }
  | { kind: "ul" | "ol"; items: string[] };

export function parseBlocks(text: string): Block[] {
  const blocks: Block[] = [];
  for (const raw of normalizeChatText(text).split("\n")) {
    const line = raw.trimEnd();
    if (!line.trim()) {
      blocks.push({ kind: "p", lines: [] }); // blank line = paragraph break
      continue;
    }
    const m = BULLET.exec(line);
    const last = blocks[blocks.length - 1];
    if (m) {
      const kind = NUMBERED.test(line) ? "ol" : "ul";
      if (last && last.kind === kind) last.items.push(m[1]);
      else blocks.push({ kind, items: [m[1]] });
    } else if (last && last.kind === "p" && last.lines.length > 0) {
      last.lines.push(line);
    } else {
      blocks.push({ kind: "p", lines: [line] });
    }
  }
  return blocks.filter((b) => (b.kind === "p" ? b.lines.length > 0 : b.items.length > 0));
}

export function ChatText({ text }: { text: string }) {
  const blocks = parseBlocks(text);
  return (
    <div className="space-y-2 break-words">
      {blocks.map((b, i) => {
        if (b.kind === "p") {
          return (
            <p key={i}>
              {b.lines.map((l, j) => (
                <Fragment key={j}>
                  {j > 0 && <br />}
                  {inline(l, `${i}-${j}`)}
                </Fragment>
              ))}
            </p>
          );
        }
        const List = b.kind;
        return (
          <List
            key={i}
            className={
              b.kind === "ul" ? "list-disc space-y-0.5 pl-5" : "list-decimal space-y-0.5 pl-5"
            }
          >
            {b.items.map((item, j) => (
              <li key={j}>{inline(item, `${i}-${j}`)}</li>
            ))}
          </List>
        );
      })}
    </div>
  );
}
