from pipeline.group.authors import AuthorRec, cluster_authors


def test_alternate_name_joins_a_translated_record():
    clusters = cluster_authors([
        AuthorRec("OL2A", "Cixin Liu", ("Liu Cixin", "刘慈欣")),
        AuthorRec("OL3A", "刘慈欣"),
    ])
    assert clusters["OL2A"] == clusters["OL3A"] == "OL2A"


def test_one_wikidata_item_joins_its_ol_records():
    clusters = cluster_authors(
        [AuthorRec("OL7A", "J.R.R. Tolkien"), AuthorRec("OL8A", "Tolkien")],
        wd_author_ids=[("Q892", "OL7A"), ("Q892", "OL8A")],
    )
    assert clusters["OL7A"] == clusters["OL8A"]


def test_ol_remote_ids_join_records():
    clusters = cluster_authors([AuthorRec("OL7A", "A", wikidata="Q1"), AuthorRec("OL9A", "B", wikidata="Q1")])
    assert clusters["OL7A"] == clusters["OL9A"]


def test_wikidata_aliases_join_by_name():
    clusters = cluster_authors(
        [AuthorRec("OL2A", "Cixin Liu"), AuthorRec("OL3A", "刘慈欣")],
        wd_author_ids=[("Q5", "OL2A")],
        wd_names=[("Q5", "刘慈欣")],
    )
    assert clusters["OL2A"] == clusters["OL3A"]


def test_a_common_name_joins_nobody():
    records = [AuthorRec(f"OL{i}A", "John Smith") for i in range(1, 6)]
    clusters = cluster_authors(records)
    assert len(set(clusters.values())) == 5


def test_a_single_latin_word_is_not_distinctive():
    clusters = cluster_authors([AuthorRec("OL1A", "Homer"), AuthorRec("OL2A", "Homer")])
    assert clusters["OL1A"] != clusters["OL2A"]


def test_unrelated_authors_stay_apart():
    clusters = cluster_authors([AuthorRec("OL1A", "Pierce Brown"), AuthorRec("OL2A", "George R. R. Martin")])
    assert clusters == {"OL1A": "OL1A", "OL2A": "OL2A"}
