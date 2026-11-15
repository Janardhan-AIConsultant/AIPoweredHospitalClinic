"""Split markdown knowledge files into small, self-describing chunks."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path

_COMMENT = re.compile(r"<!--.*?-->", re.DOTALL)
MAX_CHUNK_CHARS = 700


@dataclass(frozen=True)
class Chunk:
    id: str
    text: str
    source: str  # file stem
    title: str  # section heading


def _split_long(text: str) -> list[str]:
    if len(text) <= MAX_CHUNK_CHARS:
        return [text]
    parts, current = [], ""
    for sentence in re.split(r"(?<=[.!?])\s+", text):
        if current and len(current) + len(sentence) + 1 > MAX_CHUNK_CHARS:
            parts.append(current)
            current = sentence
        else:
            current = f"{current} {sentence}".strip()
    if current:
        parts.append(current)
    return parts


def chunk_markdown(source: str, markdown: str) -> list[Chunk]:
    """One chunk per ``##`` section (long sections are split by sentence)."""
    markdown = _COMMENT.sub("", markdown)
    chunks: list[Chunk] = []
    title = ""
    body: list[str] = []

    def flush() -> None:
        text = " ".join(" ".join(body).split())
        if not text:
            return
        for i, part in enumerate(_split_long(text)):
            digest = hashlib.sha256(f"{source}|{title}|{i}|{part}".encode()).hexdigest()[:16]
            chunks.append(Chunk(id=digest, text=f"{title}: {part}" if title else part, source=source, title=title))

    for line in markdown.splitlines():
        if line.startswith("## "):
            flush()
            title, body = line[3:].strip(), []
        elif line.startswith("# "):
            continue
        else:
            body.append(line.strip())
    flush()
    return chunks


def load_knowledge(directory: Path) -> list[Chunk]:
    chunks: list[Chunk] = []
    for path in sorted(directory.glob("*.md")):
        chunks.extend(chunk_markdown(path.stem, path.read_text(encoding="utf-8")))
    return chunks
