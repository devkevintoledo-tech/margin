"""Wikidata over SPARQL: series membership, ordinals, nesting, author ids.

Set ``WIKIDATA_SPARQL_URL`` to another endpoint (QLever serves the same
SPARQL without the public service's 60-second limit) if pages time out.
"""

from __future__ import annotations

from typing import Callable, Iterable, Iterator

import httpx

from pipeline.config import USER_AGENT
from pipeline.group.types import WdMembership, WdSeries
from pipeline.sources.http import RetryableError, check_status, with_retries

MEMBERSHIPS = """
SELECT ?item ?olid ?series ?ordinal WHERE {{
  ?item wdt:P648 ?olid .
  ?item p:P179 ?st . ?st ps:P179 ?series .
  OPTIONAL {{ ?st pq:P1545 ?ordinal . }}
  FILTER(REGEX(?olid, "^OL[0-9]+[WM]$"))
}} ORDER BY ?item ?series ?olid ?ordinal LIMIT {limit} OFFSET {offset}
"""
AUTHOR_IDS = """
SELECT ?item ?olid WHERE {{
  ?item wdt:P648 ?olid .
  FILTER(REGEX(?olid, "^OL[0-9]+A$"))
}} ORDER BY ?item ?olid LIMIT {limit} OFFSET {offset}
"""
SERIES_DETAILS = """
SELECT ?series ?label ?alias ?parent WHERE {{
  VALUES ?series {{ {values} }}
  OPTIONAL {{ ?series rdfs:label ?label . FILTER(LANG(?label) = "en") }}
  OPTIONAL {{ ?series skos:altLabel ?alias . FILTER(LANG(?alias) = "en") }}
  OPTIONAL {{ {{ ?series wdt:P179 ?parent }} UNION {{ ?series wdt:P361 ?parent }} }}
}}
"""
AUTHOR_NAMES = """
SELECT ?item ?name WHERE {{
  VALUES ?item {{ {values} }}
  {{ ?item rdfs:label ?name }} UNION {{ ?item skos:altLabel ?name }}
  FILTER(LANG(?name) IN ("en", "mul", "zh", "ja", "ko", "ru"))
}}
"""
_MAX_PARENT_DEPTH = 5


class WikidataError(RuntimeError):
    pass


def qid(uri: str) -> str:
    return uri.rsplit("/", 1)[-1]


def sparql(client: httpx.Client, url: str, query: str, *, sleep: Callable[[float], None],
           attempts: int = 5) -> list[dict[str, str]]:
    def attempt() -> list[dict[str, str]]:
        response = client.post(url, data={"query": query}, timeout=120,
                               headers={"Accept": "application/sparql-results+json", "User-Agent": USER_AGENT})
        check_status(response)
        try:
            bindings = response.json()["results"]["bindings"]
        except (ValueError, KeyError) as exc:
            raise RetryableError(f"unreadable SPARQL response: {exc}") from exc
        return [{k: v["value"] for k, v in b.items()} for b in bindings]

    return with_retries(attempt, attempts=attempts, sleep=sleep,
                        give_up=lambda exc: WikidataError(f"SPARQL page failed: {exc}"))


def paged(client: httpx.Client, url: str, template: str, *, sleep: Callable[[float], None],
          page_size: int = 10_000) -> Iterator[dict[str, str]]:
    offset = 0
    while True:
        rows = sparql(client, url, template.format(limit=page_size, offset=offset), sleep=sleep)
        yield from rows
        if len(rows) < page_size:
            return
        offset += page_size


def _batches(values: Iterable[str], size: int) -> Iterator[list[str]]:
    batch: list[str] = []
    for value in sorted(values):
        batch.append(value)
        if len(batch) == size:
            yield batch
            batch = []
    if batch:
        yield batch


def fetch_memberships(client, url, *, sleep, page_size=10_000) -> list[tuple[WdMembership, str]]:
    """``(membership, ol_id)`` pairs; ``ol_id`` is an OL work or edition id."""
    return [
        (WdMembership(qid(r["item"]), qid(r["series"]), r.get("ordinal")), r["olid"])
        for r in paged(client, url, MEMBERSHIPS, sleep=sleep, page_size=page_size)
    ]


def fetch_series(client, url, series: Iterable[str], *, sleep, batch=200) -> dict[str, WdSeries]:
    """Labels, aliases and parents for ``series``, climbing parents to depth 5."""
    found: dict[str, dict] = {}
    frontier = set(series)
    for _ in range(_MAX_PARENT_DEPTH + 1):
        frontier -= set(found)
        if not frontier:
            break
        for chunk in _batches(frontier, batch):
            values = " ".join(f"wd:{q}" for q in chunk)
            for q in chunk:
                found.setdefault(q, {"label": None, "aliases": set(), "parents": set()})
            for r in sparql(client, url, SERIES_DETAILS.format(values=values), sleep=sleep):
                entry = found[qid(r["series"])]
                entry["label"] = entry["label"] or r.get("label")
                if r.get("alias"):
                    entry["aliases"].add(r["alias"])
                if r.get("parent"):
                    entry["parents"].add(qid(r["parent"]))
        frontier = {p for e in found.values() for p in e["parents"]}
    return {
        q: WdSeries(q, e["label"], tuple(sorted(e["aliases"])), tuple(sorted(e["parents"])))
        for q, e in found.items()
    }


def fetch_author_ids(client, url, *, sleep, page_size=10_000) -> list[tuple[str, str]]:
    return [(qid(r["item"]), r["olid"]) for r in paged(client, url, AUTHOR_IDS, sleep=sleep, page_size=page_size)]


def fetch_author_names(client, url, items: Iterable[str], *, sleep, batch=200) -> list[tuple[str, str]]:
    names: set[tuple[str, str]] = set()
    for chunk in _batches(set(items), batch):
        values = " ".join(f"wd:{q}" for q in chunk)
        for r in sparql(client, url, AUTHOR_NAMES.format(values=values), sleep=sleep):
            names.add((qid(r["item"]), r["name"]))
    return sorted(names)
