"""The known-issue knowledge base: Markdown articles with a small front-matter header."""

from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

KB_DIR = Path(__file__).resolve().parents[2] / "kb"


@dataclass(frozen=True)
class Article:
    id: str
    title: str
    category: str
    escalate: bool
    body: str

    def section(self, name: str) -> str:
        m = re.search(rf"## {re.escape(name)}\n(.*?)(?=\n## |\Z)", self.body, re.S)
        return m.group(1).strip() if m else ""

    @property
    def search_text(self) -> str:
        # titles and symptoms say what farmers say; weight them by repeating
        return " ".join([self.title] * 2 + [self.section("Symptoms")] * 2 + [self.body])

    def summary(self) -> str:
        return f"{self.id} ({self.category}): {self.title}. Data signature: {self.section('What the data shows')}"


def _parse(path: Path) -> Article:
    text = path.read_text(encoding="utf-8").replace("\r\n", "\n")
    m = re.match(r"---\n(.*?)\n---\n(.*)", text, re.S)
    if not m:
        raise ValueError(f"{path.name}: missing front matter")
    meta = dict(line.split(": ", 1) for line in m.group(1).splitlines() if ": " in line)
    return Article(
        id=meta["id"],
        title=meta["title"],
        category=meta["category"],
        escalate=meta.get("escalate", "false").strip() == "true",
        body=m.group(2).strip(),
    )


@lru_cache(maxsize=4)
def load_kb(kb_dir: Path = KB_DIR) -> tuple[Article, ...]:
    return tuple(_parse(p) for p in sorted(kb_dir.glob("KB-*.md")))


def by_id(kb: tuple[Article, ...]) -> dict[str, Article]:
    return {a.id: a for a in kb}


def by_category(kb: tuple[Article, ...]) -> dict[str, Article]:
    return {a.category: a for a in kb}
