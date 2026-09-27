"""A tiny catalog that exercises every grouping rule, served over respx.

ASOIAF has three Wikidata members (one linked through an edition) and a
fourth found only in an edition's series string; Remembrance of Earth's Past
spans two spellings of its author; Red Rising needs positions to fix Dark
Age's wrong year, an adaptation to keep out, a duplicate record to merge and
a redirect to follow; Penguin Classics is an imprint; The Lord of the Rings
sits under a universe too thin to become its room.
"""

from __future__ import annotations

from urllib.parse import parse_qs

import httpx

from pipeline.tests.fixtures.dumps import dump_line, edition_line, entity, gz, sparql_json

DUMPS = {name: f"https://dumps.test/ol_dump_{name}_2026-08-31.txt.gz"
         for name in ("ratings", "reading_log", "works", "authors", "editions")}
SPARQL = "https://sparql.test/sparql"

AUTHORS = {
    "OL1A": {"name": "George R. R. Martin"},
    "OL2A": {"name": "Cixin Liu", "alternate_names": ["Liu Cixin", "刘慈欣"]},
    "OL3A": {"name": "刘慈欣"},
    "OL4A": {"name": "Pierce Brown"},
    "OL5A": {"name": "J. R. R. Tolkien", "remote_ids": {"wikidata": "Q892"}},
    "OL6A": {"name": "Rik Hoskin"},
    **{f"OL{i}A": {"name": f"Classic Author {i}"} for i in range(7, 11)},
}
# ol_id: (title, author ids, subjects, first_publish_date)
WORKS = {
    "OL10W": ("A Game of Thrones", ["OL1A"], [], "1996"),
    "OL11W": ("A Clash of Kings", ["OL1A"], [], "1998"),
    "OL12W": ("A Storm of Swords", ["OL1A"], [], "2000"),
    "OL13W": ("A Feast for Crows", ["OL1A"], [], "2005"),
    "OL20W": ("The Three-Body Problem", ["OL2A"], ["series:Remembrance of Earth's Past"], "2006"),
    "OL21W": ("The Dark Forest", ["OL3A"], [], "2008"),
    "OL22W": ("Death's End", ["OL3A"], [], "2010"),
    "OL30W": ("Red Rising", ["OL4A"], ["franchise:Red Rising"], "2014"),
    "OL31W": ("Golden Son", ["OL4A"], ["franchise:Red Rising"], "2015"),
    "OL32W": ("Morning Star", ["OL4A"], ["franchise:Red Rising"], "2016"),
    "OL33W": ("Iron Gold", ["OL4A"], ["franchise:Red Rising"], "2018"),
    "OL34W": ("Dark Age", ["OL4A"], ["franchise:Red Rising"], "2015"),
    "OL35W": ("Red Rising: Sons of Ares", ["OL6A"], ["franchise:Red Rising"], "2017"),
    "OL36W": ("Red Rising", ["OL4A"], [], None),
    "OL40W": ("Red Rising 2027 Wall Calendar", ["OL4A"], [], "2026"),
    "OL41W": ("Le Petit Livre", ["OL4A"], [], "2020"),
    "OL42W": ("A Pamphlet", ["OL4A"], [], "2020"),
    **{f"OL5{i}W": (f"Classic {i}", [f"OL{7 + i}A"], ["series:Penguin Classics"], "1900") for i in range(4)},
    "OL60W": ("The Fellowship of the Ring", ["OL5A"], [], "1954"),
    "OL61W": ("The Two Towers", ["OL5A"], [], "1954"),
    "OL62W": ("The Return of the King", ["OL5A"], [], "1955"),
    "OL63W": ("The Hobbit", ["OL5A"], [], "1937"),
    "OL70W": ("Nobody Read This", ["OL4A"], [], "2001"),
}
REDIRECTS = {"OL99W": "OL30W"}
# edition id: (work, title, extra fields)
EDITIONS = {
    "OL100M": ("OL10W", "A Game of Thrones", {}),
    "OL110M": ("OL11W", "A Clash of Kings", {}),
    "OL120M": ("OL12W", "A Storm of Swords", {}),
    "OL130M": ("OL13W", "A Feast for Crows", {"series": ["A Song of Ice and Fire ; 4"]}),
    "OL200M": ("OL20W", "The Three-Body Problem", {"series": ["Remembrance of Earth's Past ; 1"]}),
    "OL210M": ("OL21W", "The Dark Forest (Remembrance of Earth's Past Series Book 2)", {}),
    "OL220M": ("OL22W", "Death's End", {"series": ["Remembrance of Earth's Past, #3"]}),
    **{f"OL3{i}0M": (f"OL3{i}W", WORKS[f"OL3{i}W"][0], {"series": [f"Red Rising Saga ; {i + 1}"]}) for i in range(5)},
    "OL350M": ("OL35W", "Red Rising: Sons of Ares", {}),
    "OL360M": ("OL36W", "Red Rising", {}),
    "OL400M": ("OL40W", "Red Rising 2027 Wall Calendar", {}),
    "OL420M": ("OL42W", "A Pamphlet", {"number_of_pages": 20}),
    **{f"OL5{i}0M": (f"OL5{i}W", f"Classic {i}", {}) for i in range(4)},
    "OL600M": ("OL60W", "The Fellowship of the Ring", {}),
    "OL610M": ("OL61W", "The Two Towers", {}),
    "OL620M": ("OL62W", "The Return of the King", {}),
    "OL630M": ("OL63W", "The Hobbit", {}),
}
FRENCH = {"OL410M": ("OL41W", "Le Petit Livre"), "OL101M": ("OL10W", "Le Trône de fer")}
# Every selected work is shelved once; Red Rising is the popular one, and two
# ratings arrive under its redirected id.
LOGS = [w for w in WORKS if w != "OL70W"] + ["OL30W"] * 4
RATINGS = ["OL99W", "OL99W"]

MEMBERSHIPS = [  # (item, OL id, series, ordinal)
    ("Q1001", "OL10W", "Q45875", "1"),
    ("Q1002", "OL11W", "Q45875", "2"),
    ("Q1003", "OL120M", "Q45875", "3"),
    ("Q2001", "OL60W", "Q15228", "1"),
    ("Q2002", "OL61W", "Q15228", "2"),
    ("Q2003", "OL62W", "Q15228", "3"),
]
SERIES = {
    "Q45875": {"label": "A Song of Ice and Fire", "aliases": ["ASOIAF"], "parents": []},
    "Q15228": {"label": "The Lord of the Rings", "aliases": [], "parents": ["Q81"]},
    "Q81": {"label": "Middle-earth legendarium", "aliases": [], "parents": []},
}
AUTHOR_LINKS = [("Q892", "OL5A"), ("Q5", "OL2A")]
AUTHOR_NAMES = [("Q5", "刘慈欣"), ("Q892", "J.R.R. Tolkien")]

GOLDEN = """
- name: A Song of Ice and Fire
  members: [OL10W, OL11W, OL12W, OL13W]
- name: Remembrance of Earth's Past
  members: [OL20W, OL21W, OL22W]
- name: Red Rising
  members: [OL30W, OL31W, OL32W, OL33W, OL34W]
- name: The Lord of the Rings
  members: [OL60W, OL61W, OL62W]
"""


def dumps() -> dict[str, bytes]:
    works = [dump_line("/type/work", f"/works/{ol}", {
        "key": f"/works/{ol}", "title": title, "subjects": subjects,
        "authors": [{"author": {"key": f"/authors/{a}"}, "type": {"key": "/type/author_role"}} for a in authors],
        **({"first_publish_date": year} if year else {}), "covers": [int(ol[2:-1]) * 10],
    }) for ol, (title, authors, subjects, year) in WORKS.items()]
    works += [dump_line("/type/redirect", f"/works/{a}", {"location": f"/works/{b}"}) for a, b in REDIRECTS.items()]
    authors = [dump_line("/type/author", f"/authors/{ol}", {"key": f"/authors/{ol}", **rec}) for ol, rec in AUTHORS.items()]
    editions = [edition_line(ol, work, title=title, **{
        "number_of_pages": 300, "isbn_13": [f"97800000{ol[2:-1]:0>5}"], "covers": [int(ol[2:-1])], **extra,
    }) for ol, (work, title, extra) in EDITIONS.items()]
    editions += [edition_line(ol, work, languages=("fre",), title=title) for ol, (work, title) in FRENCH.items()]
    log = lambda ids: [f"/works/{w}\t\twant-to-read\t2026-01-01" for w in ids]  # noqa: E731
    return {
        "works": gz(works), "authors": gz(authors), "editions": gz(editions),
        "reading_log": gz(log(LOGS)), "ratings": gz(log(RATINGS)),
    }


def _sparql(request: httpx.Request) -> httpx.Response:
    query = parse_qs(request.content.decode())["query"][0]
    if "p:P179" in query:
        rows = [{"item": entity(i), "olid": ol, "series": entity(s), "ordinal": o} for i, ol, s, o in MEMBERSHIPS]
    elif "[0-9]+A$" in query:
        rows = [{"item": entity(q), "olid": ol} for q, ol in AUTHOR_LINKS]
    elif "VALUES ?series" in query:
        rows = []
        for q, s in SERIES.items():
            if f"wd:{q} " not in query + " ":
                continue
            rows.append({"series": entity(q), "label": s["label"]})
            rows += [{"series": entity(q), "alias": a} for a in s["aliases"]]
            rows += [{"series": entity(q), "parent": entity(p)} for p in s["parents"]]
    elif "VALUES ?item" in query:
        rows = [{"item": entity(q), "name": n} for q, n in AUTHOR_NAMES if f"wd:{q} " in query + " "]
    else:
        raise AssertionError(f"unexpected query: {query}")
    if "OFFSET" in query and int(query.rsplit("OFFSET", 1)[1]) > 0:
        rows = []
    return httpx.Response(200, json=sparql_json(rows))


def serve(router) -> None:
    """Install the world's routes on a respx router."""
    data = dumps()
    for name, url in DUMPS.items():
        router.get(url).mock(return_value=httpx.Response(200, content=data[name]))
    router.post(SPARQL).mock(side_effect=_sparql)
