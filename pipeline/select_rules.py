"""Junk rules for the select stage, loaded from ``rules/junk.yaml``."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

import yaml


@dataclass(frozen=True)
class WorkForSelect:
    ol_id: str
    title: str
    subjects: tuple[str, ...]
    author_ids: tuple[str, ...]
    max_pages: int | None  # largest page count among English editions; None = unknown
    publishers: tuple[str, ...]


@dataclass(frozen=True)
class JunkRule:
    name: str
    title: tuple[re.Pattern[str], ...]
    subject: tuple[re.Pattern[str], ...]
    publisher: tuple[re.Pattern[str], ...]

    def matches(self, work: WorkForSelect) -> bool:
        return (
            any(p.search(work.title) for p in self.title)
            or any(p.search(s) for p in self.subject for s in work.subjects)
            or self._every_publisher_matches(work.publishers)
        )

    def _every_publisher_matches(self, publishers: tuple[str, ...]) -> bool:
        # One reprint imprint (University Microfilms, GPO) among a work's
        # editions says nothing about the book; every edition must carry one.
        return bool(self.publisher and publishers) and all(
            any(p.search(pub) for p in self.publisher) for pub in publishers)


def _compile(patterns: list[str] | None) -> tuple[re.Pattern[str], ...]:
    return tuple(re.compile(p, re.IGNORECASE) for p in patterns or ())


@dataclass(frozen=True)
class JunkRules:
    min_pages: int
    rules: tuple[JunkRule, ...]

    @classmethod
    def load(cls, path: Path) -> "JunkRules":
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        return cls(
            min_pages=int(data["min_pages"]),
            rules=tuple(
                JunkRule(
                    name=r["name"],
                    title=_compile(r.get("title")),
                    subject=_compile(r.get("subject")),
                    publisher=_compile(r.get("publisher")),
                )
                for r in data["rules"]
            ),
        )

    def reason(self, work: WorkForSelect) -> str | None:
        """The name of the first rule that drops ``work``, or None to keep it.

        A work with no known page count is kept: absence of a fact is not
        evidence of a pamphlet.
        """
        if not work.author_ids:
            return "no_author"
        if work.max_pages is not None and work.max_pages < self.min_pages:
            return "short"
        for rule in self.rules:
            if rule.matches(work):
                return rule.name
        return None
